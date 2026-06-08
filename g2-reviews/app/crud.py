"""
CRUD layer — all queries use asyncpg directly for minimum overhead.
Cache-aside pattern:
  READ  → check Redis → miss → hit Postgres → store in Redis
  WRITE → hit Postgres → invalidate relevant cache keys
           → refresh materialized views asynchronously
"""
from __future__ import annotations

import math
from uuid import UUID

import asyncpg

from app.cache import cache_delete, cache_delete_pattern, cache_get, cache_set
from app.config import settings
from app.db import get_pool
from app.schemas import (
    ProductCreate,
    ProductStats,
    ReviewCreate,
    ReviewOut,
    ReviewPage,
    ReviewUpdate,
)

# ─── Cache key helpers ────────────────────────────────────────────────────────

def _k_review(review_id: UUID) -> str:
    return f"review:{review_id}"

def _k_list(product_id: UUID, page: int, size: int, rating: int | None) -> str:
    return f"reviews:product:{product_id}:p{page}:s{size}:r{rating or 'all'}"

def _k_stats(product_id: UUID) -> str:
    return f"stats:product:{product_id}"

def _k_top(product_id: UUID) -> str:
    return f"top:product:{product_id}"

def _k_list_pattern(product_id: UUID) -> str:
    return f"reviews:product:{product_id}:*"


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

async def create_review(data: ReviewCreate) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
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
        # Refresh materialized views inside the same connection while hot
        await _refresh_views(conn)

    result = dict(row)
    # Invalidate list + stats caches for this product
    await _invalidate_product_caches(data.product_id)
    return result


# ─── Reviews — READ ───────────────────────────────────────────────────────────

async def get_review(review_id: UUID) -> dict | None:
    key = _k_review(review_id)
    cached = await cache_get(key)
    if cached is not None:
        return cached

    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM reviews WHERE id = $1", review_id)
    if row is None:
        return None

    result = _row_to_dict(row)
    await cache_set(key, result, settings.cache_ttl_review)
    return result


async def list_reviews(
    product_id: UUID,
    page: int = 1,
    size: int = 20,
    rating: int | None = None,
) -> ReviewPage:
    key = _k_list(product_id, page, size, rating)
    cached = await cache_get(key)
    if cached is not None:
        return ReviewPage(**cached)

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
    page_obj = ReviewPage(
        items=[ReviewOut(**_row_to_dict(r)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total else 0,
    )
    await cache_set(key, page_obj.model_dump(mode="json"), settings.cache_ttl_list)
    return page_obj


async def get_product_stats(product_id: UUID) -> dict | None:
    key = _k_stats(product_id)
    cached = await cache_get(key)
    if cached is not None:
        return cached

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM mv_product_review_stats WHERE product_id = $1", product_id
    )
    if row is None:
        return None

    result = _row_to_dict(row)
    await cache_set(key, result, settings.cache_ttl_stats)
    return result


async def get_top_reviews(product_id: UUID) -> list[dict]:
    key = _k_top(product_id)
    cached = await cache_get(key)
    if cached is not None:
        return cached

    pool = get_pool()
    rows = await pool.fetch(
        "SELECT * FROM mv_top_reviews WHERE product_id=$1 ORDER BY helpful_count DESC",
        product_id,
    )
    result = [_row_to_dict(r) for r in rows]
    await cache_set(key, result, settings.cache_ttl_top_reviews)
    return result


# ─── Reviews — UPDATE ─────────────────────────────────────────────────────────

async def update_review(review_id: UUID, data: ReviewUpdate) -> dict | None:
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        return await get_review(review_id)

    set_clause = ", ".join(f"{col} = ${i+2}" for i, col in enumerate(fields))
    values = [review_id] + list(fields.values())

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE reviews SET {set_clause} WHERE id = $1 RETURNING *",
            *values,
        )
        if row is None:
            return None
        await _refresh_views(conn)

    result = _row_to_dict(row)
    product_id = result["product_id"]
    await cache_delete(_k_review(review_id))
    await _invalidate_product_caches(UUID(str(product_id)))
    await cache_set(_k_review(review_id), result, settings.cache_ttl_review)
    return result


# ─── Reviews — DELETE ─────────────────────────────────────────────────────────

async def delete_review(review_id: UUID) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM reviews WHERE id=$1 RETURNING product_id", review_id
        )
        if row is None:
            return False
        await _refresh_views(conn)

    await cache_delete(_k_review(review_id))
    await _invalidate_product_caches(UUID(str(row["product_id"])))
    return True


# ─── Helpful vote ─────────────────────────────────────────────────────────────

async def increment_helpful(review_id: UUID) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE reviews SET helpful_count = helpful_count + 1 WHERE id=$1 RETURNING *",
        review_id,
    )
    if row is None:
        return None
    result = _row_to_dict(row)
    await cache_delete(_k_review(review_id))
    await cache_set(_k_review(review_id), result, settings.cache_ttl_review)
    return result


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _refresh_views(conn: asyncpg.Connection) -> None:
    await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_product_review_stats")
    await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_top_reviews")


async def _invalidate_product_caches(product_id: UUID) -> None:
    await cache_delete(_k_stats(product_id), _k_top(product_id))
    await cache_delete_pattern(_k_list_pattern(product_id))


def _row_to_dict(row: asyncpg.Record) -> dict:
    result = {}
    for k, v in row.items():
        # asyncpg returns Decimal for NUMERIC — convert to float for JSON
        if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
            result[k] = float(v)
        else:
            result[k] = v
    return result
