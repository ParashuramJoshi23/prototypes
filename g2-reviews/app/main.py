from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.cache import init_cache, close_cache
from app.db import init_db, close_db
from app.crud import warm_all_caches
from app.routers.reviews import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_cache()
    # Pre-load all materialized-view data and first-page lists into Redis
    # so the very first request to any read endpoint is never a cold miss.
    await warm_all_caches()
    yield
    await close_db()
    await close_cache()


app = FastAPI(
    title="G2 Reviews API",
    description=(
        "High-performance CRUD for G2-style product reviews. "
        "P95 target: <5 ms. Stack: asyncpg + write-through Redis + "
        "pre-materialized PostgreSQL views + response-level byte caching."
    ),
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

app.include_router(router, prefix="/api/v1")


@app.get("/healthz", include_in_schema=False)
async def health():
    return {"status": "ok"}
