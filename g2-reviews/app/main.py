from contextlib import asynccontextmanager

import orjson
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.cache import init_cache, close_cache
from app.db import init_db, close_db
from app.routers.reviews import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_cache()
    yield
    await close_db()
    await close_cache()


app = FastAPI(
    title="G2 Reviews API",
    description="High-performance CRUD for G2-style product reviews. "
                "P99 target: <50 ms. Stack: asyncpg + Redis cache-aside + "
                "PostgreSQL materialized views.",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,  # faster JSON serialisation
)

app.include_router(router, prefix="/api/v1")


@app.get("/healthz", include_in_schema=False)
async def health():
    return {"status": "ok"}
