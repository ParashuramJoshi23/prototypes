"""asyncpg connection pool, shared by the agent worker and the token server.

The pool is process-global and created lazily. ``init_db()`` is idempotent and
also applies the schema (``migrations/init.sql``), so each process self-heals a
missing schema even if it didn't start Postgres via docker-compose.
"""
from __future__ import annotations

from pathlib import Path

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None
_SCHEMA_FILE = Path(__file__).resolve().parent.parent / "migrations" / "init.sql"


async def init_db() -> None:
    global _pool
    if _pool is not None:
        return
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        command_timeout=10,
    )
    await _ensure_schema()


async def _ensure_schema() -> None:
    ddl = _SCHEMA_FILE.read_text()
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(ddl)  # idempotent: CREATE TABLE IF NOT EXISTS ...


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    assert _pool is not None, "DB pool not initialised — call init_db() first"
    return _pool
