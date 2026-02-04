import os

APP_NAME = os.getenv("APP_NAME", "video-pipeline")
ENV = os.getenv("ENV", "local")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_TOPIC_UPLOAD = os.getenv("KAFKA_TOPIC_UPLOAD", "video.uploaded")
KAFKA_TOPIC_TRANSCRIPT = os.getenv("KAFKA_TOPIC_TRANSCRIPT", "video.transcript")
KAFKA_TOPIC_SUMMARY = os.getenv("KAFKA_TOPIC_SUMMARY", "video.summary")
KAFKA_TOPIC_BULLETS = os.getenv("KAFKA_TOPIC_BULLETS", "video.bullets")
KAFKA_TOPIC_ACTION_ITEMS = os.getenv("KAFKA_TOPIC_ACTION_ITEMS", "video.action_items")
KAFKA_TOPIC_TRANSLATION = os.getenv("KAFKA_TOPIC_TRANSLATION", "video.translation")
KAFKA_TOPIC_THUMBNAIL = os.getenv("KAFKA_TOPIC_THUMBNAIL", "video.thumbnail")
KAFKA_TOPIC_COMPLETE = os.getenv("KAFKA_TOPIC_COMPLETE", "video.complete")
KAFKA_TOPIC_DLQ = os.getenv("KAFKA_TOPIC_DLQ", "video.dlq")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./data/uploads")
THUMBNAIL_DIR = os.getenv("THUMBNAIL_DIR", "./data/thumbnails")

EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@example.com")
EMAIL_TO = os.getenv("EMAIL_TO", "user@example.com")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "0"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
