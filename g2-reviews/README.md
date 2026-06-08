# G2 Reviews — High-Performance CRUD Service

FastAPI service for G2-style product reviews targeting **P95 < 5 ms** on all read paths.

## Architecture

```
                     ┌──────────────────────────────────────────┐
  Request ──────────▶│  FastAPI (uvloop, 4 workers, ORJSONResp) │
                     └──────────────┬───────────────────────────┘
                                    │
                     ┌──────────────▼───────────────────────────┐
                     │        Redis (write-through cache)        │
                     │  key=pre-serialised JSON bytes            │
                     │  hit → Response(raw_bytes)  [~1 ms]       │
                     └──────────────┬───────────────────────────┘
                               miss │ (cold start only)
                     ┌──────────────▼───────────────────────────┐
                     │  asyncpg pool (min5/max20, prep-stmts)    │
                     │  Postgres 16 + materialized views         │
                     └──────────────────────────────────────────┘
```

## Why P95 < 5 ms is achievable

| Optimisation | Detail |
|---|---|
| **Response-level byte caching** | Redis stores pre-serialised orjson bytes. Cache hit = `redis GET` + `Response(bytes)`. Zero Pydantic, zero re-serialisation. |
| **Write-through** | Every `POST`/`PATCH`/`DELETE` writes the new state to Redis before returning. No lazy re-population lag. |
| **Startup pre-warm** | `warm_all_caches()` loads all MV data + first-page lists into Redis on boot. First request is never a cold miss. |
| **Background MV refresh** | `asyncio.create_task(_bg_refresh_and_warm)` decouples `REFRESH MATERIALIZED VIEW` from the write response. Writes don't pay the MV cost. |
| **asyncpg** | Binary Postgres protocol + 100 prepared-statement cache per connection. |
| **hiredis** | C extension for Redis protocol parsing (`redis[hiredis]`). |
| **Longer TTLs** | 30 min TTLs are safe because write-through keeps cache fresh. Short TTLs that cause frequent misses are the enemy of P95. |
| **CONCURRENT MV refresh** | `REFRESH MATERIALIZED VIEW CONCURRENTLY` — no read lock, reads keep serving from Redis during refresh. |
| **Targeted indexes** | `(product_id, created_at DESC)`, `(product_id, rating)` — miss-path DB queries hit index-only scans. |

## Cache keys and TTLs

| Key pattern | TTL | Updated by |
|-------------|-----|------------|
| `review:{id}` | 30 min | write-through on create/update; deleted on delete |
| `reviews:product:{id}:p*` | 5 min | invalidated by background task after writes; page-1 pre-warmed on startup |
| `stats:product:{id}` | 30 min | write-through by background MV refresh task |
| `top:product:{id}` | 30 min | write-through by background MV refresh task |

## Latency budget (read path, cache hit)

```
Redis GET          ~0.3–0.5 ms  (hiredis + local network)
.encode() bytes    ~0.01 ms
FastAPI routing    ~0.2 ms
Response()         ~0.05 ms
──────────────────────────────
Total              ~0.6–0.8 ms  (well inside 5 ms)
```

Cache miss adds one asyncpg query (2–5 ms) but only happens on cold start,
post-TTL-expiry (30 min), or the first request after a write invalidates a list page.

## Materialized views

`mv_product_review_stats` — rating distribution + aggregate per product  
`mv_top_reviews` — top-10 verified reviews per product by helpful_count

Both are refreshed `CONCURRENTLY` in a background task after every mutating request.

## Endpoints

```
POST   /api/v1/products
GET    /api/v1/products/{id}
POST   /api/v1/reviews
GET    /api/v1/reviews/{id}                            ← raw bytes from Redis
GET    /api/v1/products/{id}/reviews?page&size&rating  ← raw bytes from Redis
PATCH  /api/v1/reviews/{id}
DELETE /api/v1/reviews/{id}
POST   /api/v1/reviews/{id}/helpful
GET    /api/v1/products/{id}/stats                     ← MV, always warm
GET    /api/v1/products/{id}/top-reviews               ← MV, always warm
```

## Quick Start

```bash
cd g2-reviews
docker compose up -d

# Seed data (optional — warm_all_caches runs automatically on startup)
pip install asyncpg
python scripts/seed.py

# Interactive docs
open http://localhost:8002/docs
```
