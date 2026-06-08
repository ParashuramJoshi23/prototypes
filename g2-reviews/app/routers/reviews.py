from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app import crud
from app.schemas import (
    ProductCreate,
    ProductOut,
    ProductStats,
    ReviewCreate,
    ReviewOut,
    ReviewPage,
    ReviewUpdate,
)

router = APIRouter()


# ─── Products ─────────────────────────────────────────────────────────────────

@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(body: ProductCreate):
    return await crud.create_product(body)


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: UUID):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# ─── Reviews — CRUD ───────────────────────────────────────────────────────────

@router.post("/reviews", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
async def create_review(body: ReviewCreate):
    product = await crud.get_product(body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return await crud.create_review(body)


@router.get("/reviews/{review_id}", response_model=ReviewOut)
async def get_review(review_id: UUID):
    review = await crud.get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@router.get("/products/{product_id}/reviews", response_model=ReviewPage)
async def list_reviews(
    product_id: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    rating: int | None = Query(None, ge=1, le=5),
):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return await crud.list_reviews(product_id, page, size, rating)


@router.patch("/reviews/{review_id}", response_model=ReviewOut)
async def update_review(review_id: UUID, body: ReviewUpdate):
    review = await crud.update_review(review_id, body)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(review_id: UUID):
    deleted = await crud.delete_review(review_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Review not found")


@router.post("/reviews/{review_id}/helpful", response_model=ReviewOut)
async def mark_helpful(review_id: UUID):
    review = await crud.increment_helpful(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


# ─── Analytics (materialized views) ──────────────────────────────────────────

@router.get("/products/{product_id}/stats", response_model=ProductStats)
async def product_stats(product_id: UUID):
    stats = await crud.get_product_stats(product_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Product not found or no reviews yet")
    return stats


@router.get("/products/{product_id}/top-reviews", response_model=list[ReviewOut])
async def top_reviews(product_id: UUID):
    return await crud.get_top_reviews(product_id)
