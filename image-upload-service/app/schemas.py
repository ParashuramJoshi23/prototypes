from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from app.models import PhotoStatus


class UserCreate(BaseModel):
    email: str
    username: str


class UserOut(BaseModel):
    id: UUID
    email: str
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadRequest(BaseModel):
    user_id: UUID
    filename: str
    content_type: str = "image/jpeg"
    is_private: bool = False


class UploadResponse(BaseModel):
    photo_id: UUID
    upload_url: str
    s3_key: str
    method: Literal["PUT"]
    expires_in: int


class PhotoOut(BaseModel):
    id: UUID
    user_id: UUID
    filename: str
    s3_key: str
    processed_s3_key: Optional[str]
    is_private: bool
    status: PhotoStatus
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ViewUrlResponse(BaseModel):
    photo_id: UUID
    url: str
    expires_in: int
    via: Literal["cloudfront", "s3"]
