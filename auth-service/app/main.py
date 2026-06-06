from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, oauth, scim, sso

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema management is handled by Alembic: `alembic upgrade head`
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "Authentication service supporting username/password + JWT, "
        "OAuth 2.0 (Google, GitHub), OIDC-based SSO, and SCIM 2.0."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(sso.router)
app.include_router(scim.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}
