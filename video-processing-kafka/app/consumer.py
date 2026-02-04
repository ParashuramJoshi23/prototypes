import json
import threading
import time
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

from app.config import KAFKA_BROKER, KAFKA_TOPIC_TRANSCRIPT, KAFKA_TOPIC_UPLOAD
from app.logging_config import configure_logging, get_logger
from app.tasks import (
    add_action_items,
    add_bulletpoints,
    add_summary,
    create_thumbnail,
    generate_transcript,
    translate_language,
)

configure_logging("kafka-consumer")
logger = get_logger(__name__)


def _create_consumer(topic: str, group_id: str) -> KafkaConsumer:
    consumer = None
    while consumer is None:
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=KAFKA_BROKER,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                group_id=group_id,
            )
        except NoBrokersAvailable:
            logger.warning("kafka not ready, retrying in 3s", trace_id="-")
            time.sleep(3)
    return consumer


def _consume_loop(topic: str, group_id: str, handler, label: str) -> None:
    consumer = _create_consumer(topic, group_id)
    logger.info("%s consumer started", label, trace_id="-")
    for message in consumer:
        handler(message.value)
        time.sleep(0.05)


def _handle_upload(payload: dict) -> None:
    video_id = payload.get("video_id")
    filename = payload.get("filename")
    file_path = payload.get("file_path")
    trace_id = payload.get("trace_id", "-")
    if not video_id:
        logger.warning("missing video_id", trace_id=trace_id)
        return
    logger.info("received upload event", trace_id=trace_id)
    generate_transcript.apply_async(args=[video_id, filename, trace_id])
    translate_language.apply_async(args=["", video_id, trace_id])
    create_thumbnail.apply_async(args=["", video_id, file_path, trace_id])


def _handle_summary(payload: dict) -> None:
    video_id = payload.get("video_id")
    trace_id = payload.get("trace_id", "-")
    if not video_id:
        logger.warning("missing video_id", trace_id=trace_id)
        return
    logger.info("received transcript event (summary)", trace_id=trace_id)
    add_summary.apply_async(args=[""], kwargs={"video_id": video_id, "trace_id": trace_id})


def _handle_bullets(payload: dict) -> None:
    video_id = payload.get("video_id")
    trace_id = payload.get("trace_id", "-")
    if not video_id:
        logger.warning("missing video_id", trace_id=trace_id)
        return
    logger.info("received transcript event (bullets)", trace_id=trace_id)
    add_bulletpoints.apply_async(args=[""], kwargs={"video_id": video_id, "trace_id": trace_id})


def _handle_action_items(payload: dict) -> None:
    video_id = payload.get("video_id")
    trace_id = payload.get("trace_id", "-")
    if not video_id:
        logger.warning("missing video_id", trace_id=trace_id)
        return
    logger.info("received transcript event (action items)", trace_id=trace_id)
    add_action_items.apply_async(args=[""], kwargs={"video_id": video_id, "trace_id": trace_id})


def consume():
    threads = [
        threading.Thread(
            target=_consume_loop,
            args=(KAFKA_TOPIC_UPLOAD, "video-upload", _handle_upload, "upload"),
            daemon=True,
        ),
        threading.Thread(
            target=_consume_loop,
            args=(KAFKA_TOPIC_TRANSCRIPT, "video-summary", _handle_summary, "summary"),
            daemon=True,
        ),
        threading.Thread(
            target=_consume_loop,
            args=(KAFKA_TOPIC_TRANSCRIPT, "video-bullets", _handle_bullets, "bullets"),
            daemon=True,
        ),
        threading.Thread(
            target=_consume_loop,
            args=(
                KAFKA_TOPIC_TRANSCRIPT,
                "video-action-items",
                _handle_action_items,
                "action-items",
            ),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    consume()
