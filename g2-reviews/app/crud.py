"""
Read path:  Redis raw-bytes → Response (zero Pydantic overhead on cache hit)
Write path: DB → write-through cache → asyncio.create_task(background MV refresh)

Background refresh:
  REFRESH MATERIALIZED VIEW CONCURRENTLY → re-warm stats + top-review caches
  Decoupled from the write response so mutations never pay the MV refresh cost.

Startup:
  warm_all_caches() pre-loads every product's stats, top-reviews, and first
  page of reviews so the first request to each endpoint is never a cold miss.
"""
from __future__ import annotations

import asyncio
import math
from uuid import UUID

import asyncpg

from app.cache import (
    cache_delete,
    cache_delete_pattern,
    cache_get_raw,
    cache_set_obj,
)
from app.config import settings
from app.db import get_pool
from app.schemas import ProductCreate, ReviewCreate, ReviewUpdate

# ─── Cache key helpers ────────────────────────────────────────────────────────

def _k_review(review_id) -> str:
    return f"review:{review_id}"

def _k_list(product_id, page: int, size: int, rating: int | None) -> str:
    return f"reviews:product:{product_id}:p{page}:s{size}:r{rating or 'all'}"

def _k_stats(product_id) -> str:
    return f"stats:product:{product_id}"

def _k_top(product_id) -> str:
    return f"top:product:{product_id}"

def _k_list_pattern(product_id) -> str:
    return f"reviews:product:{product_id}:*"


# ─── Startup pre-warm ─────────────────────────────────────────────────────────

async def warm_all_caches() -> None:
    """
    Called once at startup. Loads all materialized-view data and the first
    page of reviews per product into Redis so cold-miss paths never fire
    during normal operation.
    """
    pool = get_pool()

    stats_rows = await pool.fetch("SELECT * FROM mv_product_review_stats")
    product_ids: list = []
    for row in stats_rows:
        pid = row["product_id"]
        product_ids.append(pid)
        await cache_set_obj(_k_stats(pid), _row_to_dict(row), settings.cache_ttl_stats)

    for pid in product_ids:
        top_rows = await pool.fetch(
            "SELECT * FROM mv_top_reviews WHERE product_id=$1 ORDER BY helpful_count DESC",
            pid,
        )
        await cache_set_obj(
            _k_top(pid),
            [_row_to_dict(r) for r in top_rows],
            settings.cache_ttl_top_reviews,
        )

        # Warm individual reviews + first list page per product
        rev_rows = await pool.fetch(
            "SELECT * FROM reviews WHERE product_id=$1 ORDER BY created_at DESC LIMIT 20",
            pid,
        )
        items = []
        for row in rev_rows:
            d = _row_to_dict(row)
            await cache_set_obj(_k_review(d["id"]), d, settings.cache_ttl_review)
            items.append(d)

        count_row = await pool.fetchrow(
            "SELECT COUNT(*) FROM reviews WHERE product_id=$1", pid
        )
        total = count_row["count"]
        await cache_set_obj(
            _k_list(pid, 1, 20, None),
            {"items": items, "total": total, "page": 1, "size": 20,
             "pages": math.ceil(total / 20) if total else 0},
            settings.cache_ttl_list,
        )


# ─── Background MV refresh + write-through ────────────────────────────────────

async def _bg_refresh_and_warm(product_id: UUID) -> None:
    """
    Runs as a fire-and-forget task after any mutating operation.
    Refreshes both materialized views then writes-through the updated
    stats and top-reviews into Redis.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_product_review_stats"
            )
            await conn.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_top_reviews"
            )
            stats_row = await conn.fetchrow(
                "SELECT * FROM mv_product_review_stats WHERE product_id=$1", product_id
            )
            if stats_row:
                await cache_set_obj(
                    _k_stats(product_id), _row_to_dict(stats_row), settings.cache_ttl_stats
                )
            top_rows = await conn.fetch(
                "SELECT * FROM mv_top_reviews WHERE product_id=$1 ORDER BY helpful_count DESC",
                product_id,
            )
            await cache_set_obj(
                _k_top(product_id),
                [_row_to_dict(r) for r in top_rows],
                settings.cache_ttl_top_reviews,
            )
        # Paginated lists can't be computed without knowing every page combo;
        # invalidate them so the next read rebuilds from DB and re-warms.
        await cache_delete_pattern(_k_list_pattern(product_id))
    except Exception:
        pass  # background task — never crash the server


# ─── Products ─────────────────────────────────────────────────────────────────

async def create_product(data: ProductCreate) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO products (name, category, slug)
        VALUES ($1, $2, $3)
        RETURNING id, name, category, slug, created_at
        """,
        data.name, data.category, data.slug,
    )
    return dict(row)


async def get_product(product_id: UUID) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, category, slug, created_at FROM products WHERE id = $1",
        product_id,
    )
    return dict(row) if row else None


# ─── Reviews — CREATE ─────────────────────────────────────────────────────────

async def create_review(data: ReviewCreate) -> bytes:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO reviews
            (product_id, reviewer_name, reviewer_title, reviewer_company,
             rating, title, body, pros, cons, verified)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        RETURNING *
        """,
        data.product_id, data.reviewer_name, data.reviewer_title,
        data.reviewer_company, data.rating, data.title, data.body,
        data.pros, data.cons, data.verified,
    )
    result = _row_to_dict(row)
    # Write-through: cache the new review immediately
    raw = await cache_set_obj(_k_review(result["id"]), result, settings.cache_ttl_review)
    # Decouple MV refresh from the response path
    asyncio.create_task(_bg_refresh_and_warm(data.product_id))
    return raw


# ─── Reviews — READ ───────────────────────────────────────────────────────────

async def get_review(review_id: UUID) -> bytes | None:
    """Returns pre-serialised bytes for direct Response use. None = not found."""
    key = _k_review(review_id)
    raw = await cache_get_raw(key)
    if raw is not None:
        return raw
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM reviews WHERE id = $1", review_id)
    if row is None:
        return None
    return await cache_set_obj(key, _row_to_dict(row), settings.cache_ttl_review)


async def list_reviews(
    product_id: UUID,
    page: int = 1,
    size: int = 20,
    rating: int | None = None,
) -> bytes:
    """Returns pre-serialised ReviewPage bytes."""
    key = _k_list(product_id, page, size, rating)
    raw = await cache_get_raw(key)
    if raw is not None:
        return raw

    pool = get_pool()
    offset = (page - 1) * size

    if rating:
        count_row = await pool.fetchrow(
            "SELECT COUNT(*) FROM reviews WHERE product_id=$1 AND rating=$2",
            product_id, rating,
        )
        rows = await pool.fetch(
            """
            SELECT * FROM reviews
            WHERE product_id=$1 AND rating=$2
            ORDER BY created_at DESC
            LIMIT $3 OFFSET $4
            """,
            product_id, rating, size, offset,
        )
    else:
        count_row = await pool.fetchrow(
            "SELECT COUNT(*) FROM reviews WHERE product_id=$1", product_id
        )
        rows = await pool.fetch(
            """
            SELECT * FROM reviews
            WHERE product_id=$1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            product_id, size, offset,
        )

    total = count_row["count"]
    page_data = {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "size": size,
        "pages": math.ceil(total / size) if total else 0,
    }
    return await cache_set_obj(key, page_data, settings.cache_ttl_list)


async def get_product_stats(product_id: UUID) -> bytes | None:
    key = _k_stats(product_id)
    raw = await cache_get_raw(key)
    if raw is not None:
        return raw
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM mv_product_review_stats WHERE product_id = $1", product_id
    )
    if row is None:
        return None
    return await cache_set_obj(key, _row_to_dict(row), settings.cache_ttl_stats)


async def get_top_reviews(product_id: UUID) -> bytes:
    key = _k_top(product_id)
    raw = await cache_get_raw(key)
    if raw is not None:
        return raw
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT * FROM mv_top_reviews WHERE product_id=$1 ORDER BY helpful_count DESC",
        product_id,
    )
    return await cache_set_obj(key, [_row_to_dict(r) for r in rows], settings.cache_ttl_top_reviews)


# ─── Reviews — UPDATE ─────────────────────────────────────────────────────────

async def update_review(review_id: UUID, data: ReviewUpdate) -> bytes | None:
    fields = data.model_dump(exclude_none=True)
    if not fields:
        return await get_review(review_id)

    set_clause = ", ".join(f"{col} = ${i+2}" for i, col in enumerate(fields))
    values = [review_id] + list(fields.values())

    pool = get_pool()
    row = await pool.fetchrow(
        f"UPDATE reviews SET {set_clause} WHERE id = $1 RETURNING *", *values
    )
    if row is None:
        return None

    result = _row_to_dict(row)
    raw = await cache_set_obj(_k_review(review_id), result, settings.cache_ttl_review)
    asyncio.create_task(_bg_refresh_and_warm(UUID(str(result["product_id"]))))
    return raw


# ─── Reviews — DELETE ─────────────────────────────────────────────────────────

async def delete_review(review_id: UUID) -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "DELETE FROM reviews WHERE id=$1 RETURNING product_id", review_id
    )
    if row is None:
        return False
    await cache_delete(_k_review(review_id))
    asyncio.create_task(_bg_refresh_and_warm(UUID(str(row["product_id"]))))
    return True


# ─── Helpful vote ─────────────────────────────────────────────────────────────

async def increment_helpful(review_id: UUID) -> bytes | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE reviews SET helpful_count = helpful_count + 1 WHERE id=$1 RETURNING *",
        review_id,
    )
    if row is None:
        return None
    result = _row_to_dict(row)
    return await cache_set_obj(_k_review(review_id), result, settings.cache_ttl_review)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _row_to_dict(row: asyncpg.Record) -> dict:
    result = {}
    for k, v in row.items():
        # asyncpg returns Decimal for NUMERIC columns — convert to float for orjson
        if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
            result[k] = float(v)
        else:
            result[k] = v
    return result
