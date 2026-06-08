import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app import cache, crud, s3
from app.config import KAFKA_TOPIC_POST_CREATED
from app.db import Base, engine, get_db
from app.kafka_producer import send_event
from app.schemas import (
    CreatePostRequest,
    CreatePostResponse,
    HashtagCount,
    HashtagPost,
    HashtagTopPosts,
    MarkReadRequest,
    NotificationOut,
    PostOut,
    UserCreate,
    UserOut,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    s3.ensure_bucket()
    yield


app = FastAPI(title="Hashtag Service", lifespan=lifespan)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Users ──────────────────────────────────────────────────────────────────────

@app.post("/users", response_model=UserOut, status_code=201)
def create_user(req: UserCreate, db: Session = Depends(get_db)):
    """Create or return an existing user (idempotent on email)."""
    return crud.get_or_create_user(db, username=req.username, email=req.email)


@app.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Posts ──────────────────────────────────────────────────────────────────────

@app.post("/posts", response_model=CreatePostResponse, status_code=201)
def create_post(req: CreatePostRequest, db: Session = Depends(get_db)):
    """
    Create a post. Two flows:

    Text-only post (no media_filename):
      POST /posts  →  post is immediately 'active', post.created Kafka event fired.

    Media post (media_filename provided):
      POST /posts  →  post created as 'draft', pre-signed S3 PUT URL returned.
      Client uploads file directly to S3 using that URL.
      POST /posts/{post_id}/confirm  →  post goes 'active', post.created event fired.
    """
    if not crud.get_user(db, req.user_id):
        raise HTTPException(status_code=404, detail="User not found")

    has_media  = bool(req.media_filename)
    s3_key     = None
    upload_url = None
    expires_in = None

    if has_media:
        ext    = req.media_filename.rsplit(".", 1)[-1].lower() if "." in req.media_filename else "bin"
        s3_key = f"posts/{uuid.uuid4().hex}/{req.media_filename}"
        result = s3.generate_upload_url(s3_key, req.media_content_type or "application/octet-stream")
        upload_url = result["url"]
        expires_in = result["expires_in"]

    status = "draft" if has_media else "active"
    post   = crud.create_post(db, user_id=req.user_id, caption=req.caption, media_s3_key=s3_key, status=status)

    if not has_media:
        _fire_post_created(post)

    return CreatePostResponse(
        post_id=post.id,
        upload_url=upload_url,
        s3_key=s3_key,
        method="PUT" if has_media else None,
        expires_in=expires_in,
        message="Upload media to upload_url, then call /confirm" if has_media else "Post published",
    )


@app.post("/posts/{post_id}/confirm", response_model=PostOut)
def confirm_post(post_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Call this after the client has uploaded media to S3.
    Transitions the post from 'draft' → 'active' and fires the post.created event.
    """
    post = crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.status == "active":
        raise HTTPException(status_code=409, detail="Post is already active")
    if post.status != "draft":
        raise HTTPException(status_code=409, detail=f"Cannot confirm post in state '{post.status}'")

    post = crud.activate_post(db, post)
    _fire_post_created(post)
    return _post_out(post)


@app.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: uuid.UUID, db: Session = Depends(get_db)):
    post = crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return _post_out(post)


@app.get("/posts/{post_id}/media-url")
def get_media_url(post_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return a time-limited pre-signed GET URL to view the post's media."""
    post = crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if not post.media_s3_key:
        raise HTTPException(status_code=404, detail="Post has no media")
    return s3.generate_download_url(post.media_s3_key)


# ── Hashtags ───────────────────────────────────────────────────────────────────

@app.get("/hashtags/{tag}/count", response_model=HashtagCount)
def get_hashtag_count(tag: str, db: Session = Depends(get_db)):
    """
    Return the total post count for a hashtag.
    Served from Redis cache (TTL=CACHE_COUNT_TTL) when warm; falls back to Postgres.
    """
    tag = tag.lstrip("#").lower()

    cached = cache.get_cached_count(tag)
    if cached is not None:
        return HashtagCount(tag=tag, post_count=cached)

    hashtag = crud.get_hashtag(db, tag)
    if not hashtag:
        raise HTTPException(status_code=404, detail=f"Hashtag #{tag} not found")

    cache.set_cached_count(tag, hashtag.post_count)
    return HashtagCount(tag=tag, post_count=hashtag.post_count)


@app.get("/hashtags/{tag}/posts", response_model=HashtagTopPosts)
def get_top_posts(tag: str, db: Session = Depends(get_db)):
    """
    Return the top 100 most-recent active posts for a hashtag.
    Served from Redis JSON cache (TTL=CACHE_TOP100_TTL) when warm.
    """
    tag = tag.lstrip("#").lower()

    hashtag = crud.get_hashtag(db, tag)
    if not hashtag:
        raise HTTPException(status_code=404, detail=f"Hashtag #{tag} not found")

    cached = cache.get_cached_top100(tag)
    if cached is not None:
        return HashtagTopPosts(tag=tag, total_count=hashtag.post_count, posts=cached)

    total, posts = crud.get_top_posts_for_hashtag(db, tag, limit=100)
    posts_serialised = [
        HashtagPost(
            post_id=p.id,
            user_id=p.user_id,
            caption=p.caption,
            media_s3_key=p.media_s3_key,
            created_at=p.created_at,
            hashtags=[h.tag for h in p.hashtags],
        ).model_dump(mode="json")
        for p in posts
    ]
    cache.set_cached_top100(tag, posts_serialised)
    return HashtagTopPosts(tag=tag, total_count=total, posts=posts_serialised)


# ── Notifications ──────────────────────────────────────────────────────────────

@app.get("/notifications/{user_id}", response_model=list[NotificationOut])
def get_notifications(
    user_id: uuid.UUID,
    unread_only: bool = Query(False),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    if not crud.get_user(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return crud.get_user_notifications(db, user_id, limit=limit, unread_only=unread_only)


@app.post("/notifications/{user_id}/read")
def mark_read(user_id: uuid.UUID, req: MarkReadRequest, db: Session = Depends(get_db)):
    if not crud.get_user(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    count = crud.mark_notifications_read(db, user_id, req.notification_ids)
    return {"marked_read": count}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fire_post_created(post) -> None:
    send_event(KAFKA_TOPIC_POST_CREATED, {
        "post_id":    str(post.id),
        "user_id":    str(post.user_id),
        "caption":    post.caption,
        "created_at": post.created_at.timestamp(),
    })


def _post_out(post) -> PostOut:
    return PostOut(
        id=post.id,
        user_id=post.user_id,
        caption=post.caption,
        media_s3_key=post.media_s3_key,
        status=post.status,
        created_at=post.created_at,
        hashtags=[h.tag for h in post.hashtags],
    )
