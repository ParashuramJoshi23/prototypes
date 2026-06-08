from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://g2user:g2pass@localhost:5435/g2reviews"
    redis_url: str = "redis://localhost:6380/0"

    db_pool_min: int = 5
    db_pool_max: int = 20

    # Longer TTLs are safe because all mutating paths are write-through.
    # TTL is a last-resort safety net, not the primary freshness mechanism.
    cache_ttl_review: int = 1800      # 30 min
    cache_ttl_list: int = 300         # 5 min  (invalidated + page-1 re-warmed on write)
    cache_ttl_stats: int = 1800       # 30 min (write-through via background refresh)
    cache_ttl_top_reviews: int = 1800 # 30 min (write-through via background refresh)


settings = Settings()
