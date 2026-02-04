import os
import subprocess
import time
import uuid
from celery import Celery, Task

from app.config import (
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
    KAFKA_TOPIC_ACTION_ITEMS,
    KAFKA_TOPIC_BULLETS,
    KAFKA_TOPIC_COMPLETE,
    KAFKA_TOPIC_SUMMARY,
    KAFKA_TOPIC_THUMBNAIL,
    KAFKA_TOPIC_TRANSCRIPT,
    KAFKA_TOPIC_TRANSLATION,
    KAFKA_TOPIC_DLQ,
    THUMBNAIL_DIR,
)
from app.crud import (
    get_video,
    update_action_items,
    update_bulletpoints,
    update_status,
    update_summary,
    update_thumbnail,
    update_transcript,
    update_translation,
)
from app.db import Base, SessionLocal, engine, ensure_schema
from app.kafka import send_event
from app.logging_config import configure_logging, get_logger

celery_app = Celery("video_tasks", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.task_track_started = True
celery_app.conf.worker_send_task_events = True

configure_logging("celery-worker")
logger = get_logger(__name__)

Base.metadata.create_all(bind=engine)
ensure_schema()


class BaseTask(Task):
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 60
    retry_jitter = True
    retry_kwargs = {"max_retries": 3}

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        trace_id = "-"
        if kwargs and "trace_id" in kwargs:
            trace_id = kwargs.get("trace_id") or "-"
        elif args:
            trace_id = args[-1] if isinstance(args[-1], str) else "-"
        logger.error("task failed: %s", exc, trace_id=trace_id)
        payload = {
            "task_id": task_id,
            "task_name": self.name,
            "error": str(exc),
            "trace_id": trace_id,
        }
        try:
            send_event(KAFKA_TOPIC_DLQ, payload)
        except Exception as dlq_exc:
            logger.error("dlq publish failed: %s", dlq_exc, trace_id=trace_id)


def _with_db():
    return SessionLocal()


def _attempt_completion(db, video_id: str, trace_id: str) -> str:
    video = get_video(db, video_id)
    if not video:
        return "missing"
    if video.status == "complete":
        return "already_complete"
    required = [
        video.transcript,
        video.summary,
        video.bulletpoints,
        video.action_items,
        video.translation,
        video.thumbnail_path,
    ]
    if all(required):
        update_status(db, video_id, "complete")
        send_event(KAFKA_TOPIC_COMPLETE, {"video_id": video_id, "trace_id": trace_id})
        return "complete"
    return "pending"


@celery_app.task(name="generate_transcript", base=BaseTask)
def generate_transcript(video_id: str, filename: str, trace_id: str) -> str:
    logger.info("generate transcript", trace_id=trace_id)
    db = _with_db()
    try:
        update_status(db, video_id, "transcribing")
        time.sleep(1)
        transcript = f"Transcript for {filename}"
        update_transcript(db, video_id, transcript)
        update_status(db, video_id, "transcribed")
        send_event(KAFKA_TOPIC_TRANSCRIPT, {"video_id": video_id, "trace_id": trace_id})
        _attempt_completion(db, video_id, trace_id)
        return transcript
    finally:
        db.close()


@celery_app.task(name="add_summary", base=BaseTask)
def add_summary(_previous: str, video_id: str, trace_id: str) -> str:
    logger.info("add summary", trace_id=trace_id)
    db = _with_db()
    try:
        update_status(db, video_id, "summarizing")
        time.sleep(1)
        summary = "Summary placeholder."
        update_summary(db, video_id, summary)
        update_status(db, video_id, "summarized")
        send_event(KAFKA_TOPIC_SUMMARY, {"video_id": video_id, "trace_id": trace_id})
        _attempt_completion(db, video_id, trace_id)
        return summary
    finally:
        db.close()


@celery_app.task(name="add_bulletpoints", base=BaseTask)
def add_bulletpoints(_previous: str, video_id: str, trace_id: str) -> str:
    logger.info("add bulletpoints", trace_id=trace_id)
    db = _with_db()
    try:
        update_status(db, video_id, "bulletpoints")
        time.sleep(1)
        bullets = "- Bullet 1\n- Bullet 2"
        update_bulletpoints(db, video_id, bullets)
        update_status(db, video_id, "bulleted")
        send_event(KAFKA_TOPIC_BULLETS, {"video_id": video_id, "trace_id": trace_id})
        _attempt_completion(db, video_id, trace_id)
        return bullets
    finally:
        db.close()


@celery_app.task(name="add_action_items", base=BaseTask)
def add_action_items(_previous: str, video_id: str, trace_id: str) -> str:
    logger.info("add action items", trace_id=trace_id)
    db = _with_db()
    try:
        update_status(db, video_id, "action_items")
        time.sleep(1)
        items = "- Action 1\n- Action 2"
        update_action_items(db, video_id, items)
        update_status(db, video_id, "actioned")
        send_event(KAFKA_TOPIC_ACTION_ITEMS, {"video_id": video_id, "trace_id": trace_id})
        _attempt_completion(db, video_id, trace_id)
        return items
    finally:
        db.close()


@celery_app.task(name="translate_language", base=BaseTask)
def translate_language(_previous: str, video_id: str, trace_id: str) -> str:
    logger.info("translate via deepgram (stub)", trace_id=trace_id)
    db = _with_db()
    try:
        update_status(db, video_id, "translating")
        time.sleep(1)
        translation = "Translated text placeholder (deepgram stub)."
        update_translation(db, video_id, translation)
        update_status(db, video_id, "translated")
        send_event(KAFKA_TOPIC_TRANSLATION, {"video_id": video_id, "trace_id": trace_id})
        _attempt_completion(db, video_id, trace_id)
        return translation
    finally:
        db.close()


@celery_app.task(name="create_thumbnail", base=BaseTask)
def create_thumbnail(_previous: str, video_id: str, file_path: str, trace_id: str) -> str:
    logger.info("create thumbnail", trace_id=trace_id)
    db = _with_db()
    try:
        update_status(db, video_id, "thumbnail")
        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        thumb_name = f"{video_id}-{uuid.uuid4().hex}.jpg"
        thumb_path = os.path.join(THUMBNAIL_DIR, thumb_name)
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            file_path,
            "-ss",
            "00:00:01",
            "-vframes",
            "1",
            thumb_path,
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()}")
        update_thumbnail(db, video_id, thumb_path)
        update_status(db, video_id, "thumbnailed")
        send_event(KAFKA_TOPIC_THUMBNAIL, {"video_id": video_id, "trace_id": trace_id})
        _attempt_completion(db, video_id, trace_id)
        return thumb_path
    finally:
        db.close()


@celery_app.task(name="send_completion", base=BaseTask)
def send_completion(_previous: str, video_id: str, trace_id: str) -> str:
    logger.info("send completion message", trace_id=trace_id)
    db = _with_db()
    try:
        return _attempt_completion(db, video_id, trace_id)
    finally:
        db.close()
