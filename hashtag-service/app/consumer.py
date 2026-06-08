"""
Kafka consumer — handles all async event processing for the hashtag service.

Topic routing:
  post.created        → extract hashtags → emit hashtag.process per tag
  hashtag.process     → upsert hashtag, link to post, increment count,
                        invalidate Redis caches, emit hashtag.created /
                        hashtag.incremented + notification.inapp
  notification.inapp  → persist in-app notification to the database
"""
import json
import logging
import time
import uuid

from kafka import KafkaConsumer

from app import cache, crud
from app.config import (
    KAFKA_BROKER,
    KAFKA_TOPIC_HASHTAG_CREATED,
    KAFKA_TOPIC_HASHTAG_INCREMENTED,
    KAFKA_TOPIC_HASHTAG_PROCESS,
    KAFKA_TOPIC_NOTIFICATION_INAPP,
    KAFKA_TOPIC_POST_CREATED,
)
from app.db import SessionLocal
from app.kafka_producer import send_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_post_created(payload: dict) -> None:
    """
    Extract every hashtag from the caption and emit a hashtag.process event
    for each one. Splitting into per-tag events keeps handlers idempotent and
    allows independent retry on failure.
    """
    post_id    = payload["post_id"]
    caption    = payload["caption"]
    user_id    = payload["user_id"]
    created_at = payload.get("created_at", time.time())

    tags = crud.extract_hashtags(caption)
    logger.info("post.created post_id=%s tags=%s", post_id, tags)

    for tag in tags:
        send_event(KAFKA_TOPIC_HASHTAG_PROCESS, {
            "tag": tag,
            "post_id": post_id,
            "user_id": user_id,
            "created_at": created_at,
        })


def handle_hashtag_process(payload: dict) -> None:
    """
    Upsert the hashtag, link the post, increment the count, and update caches.

    is_new=True  → emit hashtag.created + notify the author
    is_new=False → emit hashtag.incremented
    """
    tag        = payload["tag"]
    post_id    = payload["post_id"]
    user_id    = payload["user_id"]
    created_at = float(payload.get("created_at") or time.time())

    db = SessionLocal()
    try:
        hashtag, is_new = crud.get_or_create_hashtag(db, tag)

        # Link post → hashtag in the join table (idempotent).
        crud.link_post_hashtag(db, uuid.UUID(post_id), hashtag.id)

        # Atomic SQL-level increment.
        hashtag = crud.increment_hashtag_count(db, tag)

        logger.info(
            "hashtag.process tag=#%s post_id=%s is_new=%s count=%s",
            tag, post_id, is_new, hashtag.post_count,
        )

        if is_new:
            send_event(KAFKA_TOPIC_HASHTAG_CREATED, {
                "tag": tag,
                "hashtag_id": str(hashtag.id),
                "post_id": post_id,
                "user_id": user_id,
            })
            # Notify the author who coined the hashtag.
            send_event(KAFKA_TOPIC_NOTIFICATION_INAPP, {
                "user_id": user_id,
                "type": "hashtag_created",
                "title": f"#{tag} is live!",
                "body": f"You started the #{tag} hashtag. Be the trendsetter!",
                "payload": {"tag": tag, "hashtag_id": str(hashtag.id)},
            })
        else:
            send_event(KAFKA_TOPIC_HASHTAG_INCREMENTED, {
                "tag": tag,
                "hashtag_id": str(hashtag.id),
                "post_id": post_id,
                "user_id": user_id,
                "new_count": hashtag.post_count,
            })

        # Keep Redis sorted-set index up to date.
        cache.add_post_to_sorted_set(tag, post_id, created_at)

        # Invalidate stale cached values so the next read goes to the DB.
        cache.invalidate_count(tag)
        cache.invalidate_top100(tag)

    finally:
        db.close()


def handle_notification_inapp(payload: dict) -> None:
    """Persist an in-app notification. Skips silently if the user doesn't exist."""
    user_id = payload["user_id"]

    db = SessionLocal()
    try:
        uid = uuid.UUID(user_id)
        if not crud.get_user(db, uid):
            logger.warning("notification.inapp skipped: user %s not found", user_id)
            return

        notif = crud.create_notification(
            db,
            user_id=uid,
            type=payload["type"],
            title=payload["title"],
            body=payload.get("body", ""),
            payload=payload.get("payload", {}),
        )
        logger.info("notification created id=%s user=%s type=%s", notif.id, user_id, payload["type"])
    finally:
        db.close()


# ── Dispatch table ────────────────────────────────────────────────────────────

HANDLERS = {
    KAFKA_TOPIC_POST_CREATED:       handle_post_created,
    KAFKA_TOPIC_HASHTAG_PROCESS:    handle_hashtag_process,
    KAFKA_TOPIC_NOTIFICATION_INAPP: handle_notification_inapp,
}


# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> None:
    logger.info("Connecting to Kafka broker %s", KAFKA_BROKER)
    consumer = KafkaConsumer(
        *HANDLERS.keys(),
        bootstrap_servers=KAFKA_BROKER,
        group_id="hashtag-service-consumer",
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    logger.info("Subscribed to topics: %s", list(HANDLERS.keys()))

    for message in consumer:
        topic   = message.topic
        payload = message.value
        logger.info("[%s] offset=%s payload=%s", topic, message.offset, payload)

        handler = HANDLERS.get(topic)
        if handler:
            try:
                handler(payload)
            except Exception:
                logger.exception("Unhandled error processing [%s] offset=%s", topic, message.offset)


if __name__ == "__main__":
    run()
