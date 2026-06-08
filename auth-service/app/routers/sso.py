"""Enterprise SSO via OIDC (Okta, Azure AD, Auth0, Google Workspace, etc.)"""
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token, create_refresh_token
from app.auth.sso import discover_oidc_config, generate_state, sso_auth_url, sso_exchange_code, sso_get_user
from app.config import get_settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models import OAuthAccount, Tenant, User
from app.schemas import SSOLoginRequest, TenantCreate, TenantOut, TokenResponse

router = APIRouter(prefix="/sso", tags=["sso"])
settings = get_settings()

_STATE_STORE: dict[str, str] = {}  # state → tenant_id; use Redis in production


# ── Tenant management ─────────────────────────────────────────────────────────

@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(body: TenantCreate, db: Session = Depends(get_db)):
    if db.query(Tenant).filter_by(name=body.name).first():
        raise HTTPException(status_code=409, detail="Tenant already exists")
    tenant = Tenant(**body.model_dump())
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db)):
    return db.query(Tenant).all()


@router.post("/tenants/{tenant_id}/scim-token")
def set_scim_token(tenant_id: str, token: str, db: Session = Depends(get_db)):
    """Store a hashed SCIM bearer token for a tenant."""
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.scim_token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.commit()
    return {"status": "updated"}


# ── SSO Login flow ────────────────────────────────────────────────────────────

@router.post("/login")
async def sso_login(body: SSOLoginRequest, db: Session = Depends(get_db)):
    """Look up the tenant by email domain and redirect to the OIDC provider."""
    domain = body.email.split("@")[-1]
    tenant = db.query(Tenant).filter_by(sso_domain=domain).first()
    if not tenant or not tenant.sso_issuer:
        raise HTTPException(status_code=404, detail="No SSO configured for this domain")

    try:
        oidc_config = await discover_oidc_config(tenant.sso_issuer)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OIDC discovery failed: {exc}")

    state = generate_state()
    _STATE_STORE[state] = tenant.id

    redirect_uri = f"{settings.base_url}/sso/callback"
    url = sso_auth_url(
        authorization_endpoint=oidc_config["authorization_endpoint"],
        client_id=tenant.sso_client_id,
        redirect_uri=redirect_uri,
        state=state,
    )
    return {"redirect_url": url}


@router.get("/callback", response_model=TokenResponse)
async def sso_callback(code: str, state: str, db: Session = Depends(get_db)):
    tenant_id = _STATE_STORE.pop(state, None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Invalid SSO state")

    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=400, detail="Tenant not found")

    try:
        oidc_config = await discover_oidc_config(tenant.sso_issuer)
        redirect_uri = f"{settings.base_url}/sso/callback"
        tokens = await sso_exchange_code(
            token_endpoint=oidc_config["token_endpoint"],
            client_id=tenant.sso_client_id,
            client_secret=tenant.sso_client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
        user_info = await sso_get_user(oidc_config["userinfo_endpoint"], tokens["access_token"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SSO error: {exc}")

    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="No email in SSO response")

    provider_user_id = user_info.get("sub", email)
    account = (
        db.query(OAuthAccount)
        .filter_by(provider=f"sso:{tenant_id}", provider_user_id=provider_user_id)
        .first()
    )
    if account:
        user = account.user
    else:
        user = db.query(User).filter_by(email=email).first()
        if not user:
            user = User(email=email, tenant_id=tenant_id, is_verified=True)
            db.add(user)
            db.flush()
        db.add(
            OAuthAccount(
                user_id=user.id,
                provider=f"sso:{tenant_id}",
                provider_user_id=provider_user_id,
                access_token=tokens.get("access_token"),
                refresh_token=tokens.get("refresh_token"),
            )
        )
        db.commit()
        db.refresh(user)

    access_token, expires_in = create_access_token(user.id, extra={"tenant_id": tenant_id})
    refresh_token = create_refresh_token(user.id, db)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)
