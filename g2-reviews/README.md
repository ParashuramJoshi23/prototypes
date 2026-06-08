# G2 Reviews — High-Performance CRUD Service

FastAPI service for G2-style product reviews targeting **P99 < 50 ms** on read paths.

## Performance Architecture

| Layer | Technique | Benefit |
|-------|-----------|---------|
| **asyncpg** | Binary protocol, prepared-statement cache | ~2× faster than psycopg2 |
| **asyncpg pool** | min 5 / max 20 connections | Zero connection-establishment latency |
| **Redis cache-aside** | SCAN-safe key invalidation, orjson serialisation | Reads served in < 1 ms on cache hit |
| **Materialized views** | `mv_product_review_stats`, `mv_top_reviews` | Aggregate queries pre-computed; refreshed after writes |
| **CONCURRENT refresh** | `REFRESH MATERIALIZED VIEW CONCURRENTLY` | No read lock during refresh |
| **ORJSONResponse** | orjson serialisation in FastAPI | ~10× faster than stdlib json |
| **Indexes** | `(product_id)`, `(product_id, rating)`, `(product_id, created_at DESC)` | Planner picks tight index scans |
| **uvloop + uvicorn** | Async event loop + 4 workers | High concurrency with low CPU overhead |

## Cache TTLs

| Key pattern | TTL | Invalidated on |
|-------------|-----|----------------|
| `review:{id}` | 5 min | UPDATE / DELETE that review |
| `reviews:product:{id}:*` | 1 min | Any review write for that product |
| `stats:product:{id}` | 2 min | Any review write for that product |
| `top:product:{id}` | 2 min | Any review write for that product |

## Endpoints

```
POST   /api/v1/products                          Create product
GET    /api/v1/products/{id}                     Get product

POST   /api/v1/reviews                           Create review
GET    /api/v1/reviews/{id}                      Get review  (cache-aside)
GET    /api/v1/products/{id}/reviews?page=&size=&rating=  List reviews (cached)
PATCH  /api/v1/reviews/{id}                      Update review
DELETE /api/v1/reviews/{id}                      Delete review
POST   /api/v1/reviews/{id}/helpful              Increment helpful vote

GET    /api/v1/products/{id}/stats               Aggregates from mv (cached)
GET    /api/v1/products/{id}/top-reviews         Top 10 verified reviews (cached)
```

## Quick Start

```bash
docker compose up -d

# Wait for health checks, then seed data
pip install asyncpg
python scripts/seed.py

# Interactive docs
open http://localhost:8002/docs
```

## Latency Budget (read path, cache hit)

```
Redis GET          ~0.3 ms  (local network)
FastAPI overhead   ~0.5 ms
orjson deserialise ~0.1 ms
─────────────────────────
Total              ~1 ms
```

Cache miss adds one asyncpg query (~2–5 ms for indexed lookup), well within the 50 ms P99 budget even under load.
