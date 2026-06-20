"""Configuration (env-driven via pydantic-settings)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres connection used by both the agent worker and the token server.
    database_url: str = "postgresql://interviewer:interviewer@localhost:5439/interviewer"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # Claude model the interviewer uses. Voice is latency-sensitive, so
    # claude-sonnet-4-6 / claude-haiku-4-5 are reasonable faster/cheaper swaps.
    interviewer_model: str = "claude-opus-4-8"


settings = Settings()
