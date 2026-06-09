import orjson
import redis.asyncio as aioredis
from app.config import settings

_redis: aioredis.Redis | None = None


async def init_cache() -> None:
    global _redis
    _redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def close_cache() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    assert _redis is not None, "Redis not initialised"
    return _redis


async def cache_get_raw(key: str) -> bytes | None:
    """Return pre-serialised JSON bytes for direct Response use — zero extra parsing."""
    val = await get_redis().get(key)
    return val.encode() if val else None


async def cache_set_obj(key: str, obj, ttl: int) -> bytes:
    """Serialise obj with orjson, persist to Redis, return bytes for immediate use."""
    raw = orjson.dumps(obj, default=str)
    await get_redis().set(key, raw.decode(), ex=ttl)
    return raw


async def cache_delete(*keys: str) -> None:
    if keys:
        await get_redis().delete(*keys)


async def cache_delete_pattern(pattern: str) -> None:
    redis = get_redis()
    cursor = 0
    while True:
        cursor, matched = await redis.scan(cursor, match=pattern, count=200)
        if matched:
            await redis.delete(*matched)
        if cursor == 0:
            break
