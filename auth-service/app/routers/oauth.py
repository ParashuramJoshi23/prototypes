"""OAuth routes for Google and GitHub."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token, create_refresh_token
from app.auth.oauth import (
    generate_state,
    github_auth_url,
    github_exchange_code,
    github_get_user,
    google_auth_url,
    google_exchange_code,
    google_get_user,
)
from app.config import get_settings
from app.db import get_db
from app.models import OAuthAccount, User
from app.schemas import TokenResponse

router = APIRouter(prefix="/oauth", tags=["oauth"])
settings = get_settings()

_STATE_STORE: dict[str, str] = {}  # in-memory; use Redis/DB in production


def _upsert_oauth_user(
    db: Session,
    provider: str,
    provider_user_id: str,
    email: str,
    username: str | None,
    access_token: str,
    refresh_token: str | None,
) -> User:
    account = (
        db.query(OAuthAccount)
        .filter_by(provider=provider, provider_user_id=str(provider_user_id))
        .first()
    )
    if account:
        account.access_token = access_token
        account.refresh_token = refresh_token
        db.commit()
        return account.user

    user = db.query(User).filter_by(email=email).first()
    if not user:
        user = User(email=email, username=username, is_verified=True)
        db.add(user)
        db.flush()

    db.add(
        OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=str(provider_user_id),
            access_token=access_token,
            refresh_token=refresh_token,
        )
    )
    db.commit()
    db.refresh(user)
    return user


# ── Google ────────────────────────────────────────────────────────────────────

@router.get("/google/login")
def google_login():
    state = generate_state()
    _STATE_STORE[state] = "google"
    return RedirectResponse(google_auth_url(state))


@router.get("/google/callback", response_model=TokenResponse)
async def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    if state not in _STATE_STORE:
        raise HTTPException(status_code=400, detail="Invalid state")
    del _STATE_STORE[state]

    try:
        tokens = await google_exchange_code(code)
        user_info = await google_get_user(tokens["access_token"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google error: {exc}")

    if not user_info.get("email"):
        raise HTTPException(status_code=400, detail="No email from Google")

    user = _upsert_oauth_user(
        db,
        provider="google",
        provider_user_id=user_info["sub"],
        email=user_info["email"],
        username=user_info.get("email", "").split("@")[0],
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
    )

    access_token, expires_in = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id, db)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)


# ── GitHub ────────────────────────────────────────────────────────────────────

@router.get("/github/login")
def github_login():
    state = generate_state()
    _STATE_STORE[state] = "github"
    return RedirectResponse(github_auth_url(state))


@router.get("/github/callback", response_model=TokenResponse)
async def github_callback(code: str, state: str, db: Session = Depends(get_db)):
    if state not in _STATE_STORE:
        raise HTTPException(status_code=400, detail="Invalid state")
    del _STATE_STORE[state]

    try:
        tokens = await github_exchange_code(code)
        user_info = await github_get_user(tokens["access_token"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub error: {exc}")

    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="No verified email from GitHub")

    user = _upsert_oauth_user(
        db,
        provider="github",
        provider_user_id=user_info["id"],
        email=email,
        username=user_info.get("login"),
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
    )

    access_token, expires_in = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id, db)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)
