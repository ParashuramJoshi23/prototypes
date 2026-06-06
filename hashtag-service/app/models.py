import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username   = Column(String(50), unique=True, nullable=False)
    email      = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    posts         = relationship("Post", back_populates="user")
    notifications = relationship("Notification", back_populates="user")


class Post(Base):
    __tablename__ = "posts"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    caption      = Column(Text, nullable=False)
    media_s3_key = Column(String(500))
    # draft → active (text posts skip draft); failed on processing error
    status       = Column(String(20), nullable=False, default="draft")
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user     = relationship("User", back_populates="posts")
    hashtags = relationship("Hashtag", secondary="post_hashtags", back_populates="posts")


class Hashtag(Base):
    __tablename__ = "hashtags"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # stored lowercase without leading '#'
    tag        = Column(String(100), unique=True, nullable=False)
    post_count = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    posts = relationship("Post", secondary="post_hashtags", back_populates="hashtags")


class PostHashtag(Base):
    __tablename__ = "post_hashtags"

    post_id    = Column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)
    hashtag_id = Column(UUID(as_uuid=True), ForeignKey("hashtags.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # hashtag_created | hashtag_incremented | post_tagged
    type       = Column(String(50), nullable=False)
    title      = Column(String(255), nullable=False)
    body       = Column(Text)
    is_read    = Column(Boolean, nullable=False, default=False)
    # flexible JSON bag: tag, post_id, hashtag_id, etc.
    payload    = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")
