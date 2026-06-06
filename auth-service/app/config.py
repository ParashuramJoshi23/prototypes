from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "Auth Service"
    debug: bool = False
    base_url: str = "http://localhost:8000"

    # Database
    database_url: str = "sqlite:///./auth.db"

    # JWT
    jwt_secret_key: str = "change-me-in-production-use-256-bit-key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # OAuth — Google
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/oauth/google/callback"

    # OAuth — GitHub
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:8000/oauth/github/callback"

    # SCIM
    scim_bearer_token: str = "scim-secret-token"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
