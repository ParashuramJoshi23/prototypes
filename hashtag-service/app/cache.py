"""
Redis caching layer.

Keys:
  hashtag:{tag}:count   – cached post count (string, TTL=CACHE_COUNT_TTL)
  hashtag:{tag}:top100  – JSON-serialised top-100 posts list (TTL=CACHE_TOP100_TTL)
  hashtag:{tag}:posts   – sorted set: member=post_id, score=unix timestamp
                          Used as an incrementally-updated index; capped at 100 members.
"""
import json
from typing import Optional

import redis

from app.config import CACHE_COUNT_TTL, CACHE_TOP100_TTL, REDIS_URL

_redis: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


# ── Count cache ───────────────────────────────────────────────────────────────

def get_cached_count(tag: str) -> Optional[int]:
    val = get_redis().get(f"hashtag:{tag}:count")
    return int(val) if val is not None else None


def set_cached_count(tag: str, count: int) -> None:
    get_redis().setex(f"hashtag:{tag}:count", CACHE_COUNT_TTL, count)


def invalidate_count(tag: str) -> None:
    get_redis().delete(f"hashtag:{tag}:count")


# ── Top-100 posts cache (JSON blob) ──────────────────────────────────────────

def get_cached_top100(tag: str) -> Optional[list]:
    val = get_redis().get(f"hashtag:{tag}:top100")
    return json.loads(val) if val else None


def set_cached_top100(tag: str, posts: list) -> None:
    get_redis().setex(f"hashtag:{tag}:top100", CACHE_TOP100_TTL, json.dumps(posts))


def invalidate_top100(tag: str) -> None:
    get_redis().delete(f"hashtag:{tag}:top100")


# ── Sorted-set index (incremental, survives restarts) ────────────────────────

def add_post_to_sorted_set(tag: str, post_id: str, score: float) -> None:
    """
    Add post to a sorted set keyed by creation timestamp (score).
    Trim the set to the top 100 members immediately after each insert so
    storage stays bounded even for very active hashtags.
    """
    r = get_redis()
    key = f"hashtag:{tag}:posts"
    r.zadd(key, {post_id: score})
    # Keep only the 100 highest scores (newest posts); remove older ones.
    r.zremrangebyrank(key, 0, -101)


def get_top100_post_ids(tag: str) -> list[str]:
    """Return up to 100 post IDs sorted newest-first (highest score first)."""
    return get_redis().zrevrange(f"hashtag:{tag}:posts", 0, 99)
