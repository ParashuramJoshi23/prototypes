from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://g2user:g2pass@localhost:5435/g2reviews"
    redis_url: str = "redis://localhost:6380/0"

    db_pool_min: int = 5
    db_pool_max: int = 20

    # Cache TTLs (seconds)
    cache_ttl_review: int = 300        # 5 min — single review
    cache_ttl_list: int = 60           # 1 min — paginated list
    cache_ttl_stats: int = 120         # 2 min — product stats (mv-backed)
    cache_ttl_top_reviews: int = 120   # 2 min — top reviews (mv-backed)


settings = Settings()
