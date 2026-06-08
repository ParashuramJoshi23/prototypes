from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, model_validator


# ---------- Products ----------

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category: str | None = None
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-z0-9-]+$")


class ProductOut(BaseModel):
    id: UUID
    name: str
    category: str | None
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- Reviews ----------

class ReviewCreate(BaseModel):
    product_id: UUID
    reviewer_name: str = Field(..., min_length=1, max_length=255)
    reviewer_title: str | None = Field(None, max_length=255)
    reviewer_company: str | None = Field(None, max_length=255)
    rating: int = Field(..., ge=1, le=5)
    title: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)
    pros: str | None = None
    cons: str | None = None
    verified: bool = False


class ReviewUpdate(BaseModel):
    reviewer_title: str | None = Field(None, max_length=255)
    reviewer_company: str | None = Field(None, max_length=255)
    rating: int | None = Field(None, ge=1, le=5)
    title: str | None = Field(None, min_length=1, max_length=500)
    body: str | None = Field(None, min_length=1)
    pros: str | None = None
    cons: str | None = None
    verified: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "ReviewUpdate":
        if all(v is None for v in self.model_dump().values()):
            raise ValueError("At least one field must be provided for update")
        return self


class ReviewOut(BaseModel):
    id: UUID
    product_id: UUID
    reviewer_name: str
    reviewer_title: str | None
    reviewer_company: str | None
    rating: int
    title: str
    body: str
    pros: str | None
    cons: str | None
    verified: bool
    helpful_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewPage(BaseModel):
    items: list[ReviewOut]
    total: int
    page: int
    size: int
    pages: int


# ---------- Stats (from materialized view) ----------

class ProductStats(BaseModel):
    product_id: UUID
    product_name: str
    category: str | None
    total_reviews: int
    avg_rating: float | None
    five_star: int
    four_star: int
    three_star: int
    two_star: int
    one_star: int
    verified_reviews: int
    latest_review_at: datetime | None
