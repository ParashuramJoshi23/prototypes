import json
import time
from kafka import KafkaProducer

from app.config import KAFKA_BROKER


_producer = None


def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=5,
            retry_backoff_ms=500,
        )
    return _producer


def send_event(topic: str, payload: dict) -> None:
    producer = get_producer()
    for attempt in range(3):
        try:
            producer.send(topic, payload)
            producer.flush()
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)
