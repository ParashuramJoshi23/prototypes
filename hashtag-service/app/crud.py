import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Hashtag, Notification, Post, PostHashtag, User

HASHTAG_RE = re.compile(r"#(\w+)")


def extract_hashtags(caption: str) -> list[str]:
    return list({tag.lower() for tag in HASHTAG_RE.findall(caption)})


# ── Users ─────────────────────────────────────────────────────────────────────

def get_or_create_user(db: Session, username: str, email: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(username=username, email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: uuid.UUID) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


# ── Posts ─────────────────────────────────────────────────────────────────────

def create_post(
    db: Session,
    user_id: uuid.UUID,
    caption: str,
    media_s3_key: Optional[str] = None,
    status: str = "draft",
) -> Post:
    post = Post(user_id=user_id, caption=caption, media_s3_key=media_s3_key, status=status)
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def get_post(db: Session, post_id: uuid.UUID) -> Optional[Post]:
    return db.query(Post).filter(Post.id == post_id).first()


def activate_post(db: Session, post: Post) -> Post:
    post.status = "active"
    post.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return post


# ── Hashtags ──────────────────────────────────────────────────────────────────

def get_or_create_hashtag(db: Session, tag: str) -> tuple[Hashtag, bool]:
    """Return (hashtag, is_new). Safe under concurrent inserts via retry on IntegrityError."""
    hashtag = db.query(Hashtag).filter(Hashtag.tag == tag).first()
    if hashtag:
        return hashtag, False
    try:
        hashtag = Hashtag(tag=tag, post_count=0)
        db.add(hashtag)
        db.commit()
        db.refresh(hashtag)
        return hashtag, True
    except IntegrityError:
        db.rollback()
        hashtag = db.query(Hashtag).filter(Hashtag.tag == tag).first()
        return hashtag, False


def increment_hashtag_count(db: Session, tag: str) -> Hashtag:
    # Atomic SQL-level increment avoids lost-update races when multiple
    # consumers process posts with the same hashtag simultaneously.
    db.execute(
        update(Hashtag)
        .where(Hashtag.tag == tag)
        .values(post_count=Hashtag.post_count + 1, updated_at=datetime.utcnow())
    )
    db.commit()
    return db.query(Hashtag).filter(Hashtag.tag == tag).first()


def link_post_hashtag(db: Session, post_id: uuid.UUID, hashtag_id: uuid.UUID) -> None:
    exists = db.query(PostHashtag).filter_by(post_id=post_id, hashtag_id=hashtag_id).first()
    if not exists:
        db.add(PostHashtag(post_id=post_id, hashtag_id=hashtag_id))
        db.commit()


def get_hashtag(db: Session, tag: str) -> Optional[Hashtag]:
    return db.query(Hashtag).filter(Hashtag.tag == tag).first()


def get_top_posts_for_hashtag(
    db: Session, tag: str, limit: int = 100
) -> tuple[int, list[Post]]:
    """Return (total_count, top N active posts) sorted newest-first."""
    hashtag = db.query(Hashtag).filter(Hashtag.tag == tag).first()
    if not hashtag:
        return 0, []
    posts = (
        db.query(Post)
        .join(PostHashtag, Post.id == PostHashtag.post_id)
        .filter(PostHashtag.hashtag_id == hashtag.id, Post.status == "active")
        .order_by(Post.created_at.desc())
        .limit(limit)
        .all()
    )
    return hashtag.post_count, posts


# ── Notifications ─────────────────────────────────────────────────────────────

def create_notification(
    db: Session,
    user_id: uuid.UUID,
    type: str,
    title: str,
    body: str,
    payload: dict,
) -> Notification:
    notif = Notification(user_id=user_id, type=type, title=title, body=body, payload=payload)
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def get_user_notifications(
    db: Session,
    user_id: uuid.UUID,
    limit: int = 50,
    unread_only: bool = False,
) -> list[Notification]:
    q = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    return q.order_by(Notification.created_at.desc()).limit(limit).all()


def mark_notifications_read(
    db: Session, user_id: uuid.UUID, notification_ids: list[uuid.UUID]
) -> int:
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.id.in_(notification_ids))
        .update({"is_read": True}, synchronize_session=False)
    )
    db.commit()
    return count
