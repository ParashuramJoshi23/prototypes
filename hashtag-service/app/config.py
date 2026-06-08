import os

# ── AWS / S3 ──────────────────────────────────────────────────────────────────
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")

S3_BUCKET = os.getenv("S3_BUCKET", "hashtag-media")

# App-to-S3 connection (docker-internal when using LocalStack in Compose)
S3_ENDPOINT_URL: str | None = os.getenv("S3_ENDPOINT_URL")

# Endpoint embedded in pre-signed URLs returned to clients.
# Set to http://localhost:4566 when LocalStack runs inside Docker so that
# clients outside the Docker network can still reach it.
PRESIGN_ENDPOINT_URL: str | None = os.getenv("PRESIGN_ENDPOINT_URL") or S3_ENDPOINT_URL

PRESIGN_EXPIRY_SECONDS = int(os.getenv("PRESIGN_EXPIRY_SECONDS", "3600"))

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/hashtagdb",
)

# ── Kafka ─────────────────────────────────────────────────────────────────────
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")

KAFKA_TOPIC_POST_CREATED        = "post.created"
KAFKA_TOPIC_HASHTAG_PROCESS     = "hashtag.process"
KAFKA_TOPIC_HASHTAG_CREATED     = "hashtag.created"
KAFKA_TOPIC_HASHTAG_INCREMENTED = "hashtag.incremented"
KAFKA_TOPIC_NOTIFICATION_INAPP  = "notification.inapp"

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# TTL for top-100 posts list (seconds)
CACHE_TOP100_TTL = int(os.getenv("CACHE_TOP100_TTL", "120"))
# TTL for hashtag post count (seconds)
CACHE_COUNT_TTL = int(os.getenv("CACHE_COUNT_TTL", "300"))
