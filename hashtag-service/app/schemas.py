import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Posts ─────────────────────────────────────────────────────────────────────

class CreatePostRequest(BaseModel):
    user_id: uuid.UUID
    caption: str
    media_filename: Optional[str] = None
    media_content_type: Optional[str] = None


class CreatePostResponse(BaseModel):
    post_id: uuid.UUID
    upload_url: Optional[str] = None   # pre-signed S3 PUT URL; None for text-only posts
    s3_key: Optional[str] = None
    method: Optional[str] = None       # always "PUT" when upload_url is set
    expires_in: Optional[int] = None
    message: str


class PostOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    caption: str
    media_s3_key: Optional[str]
    status: str
    created_at: datetime
    hashtags: list[str] = []

    model_config = {"from_attributes": True}


# ── Hashtags ──────────────────────────────────────────────────────────────────

class HashtagCount(BaseModel):
    tag: str
    post_count: int


class HashtagPost(BaseModel):
    post_id: uuid.UUID
    user_id: uuid.UUID
    caption: str
    media_s3_key: Optional[str]
    created_at: datetime
    hashtags: list[str]


class HashtagTopPosts(BaseModel):
    tag: str
    total_count: int
    posts: list[HashtagPost]


# ── Notifications ─────────────────────────────────────────────────────────────

class MarkReadRequest(BaseModel):
    notification_ids: list[uuid.UUID]


class NotificationOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    body: Optional[str]
    is_read: bool
    payload: Optional[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}
