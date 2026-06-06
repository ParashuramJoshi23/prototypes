import os

# ── AWS / S3 ──────────────────────────────────────────────────────────────────
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")

S3_BUCKET = os.getenv("S3_BUCKET", "photos")

# App-to-S3 connection (docker-internal when using LocalStack in Compose)
S3_ENDPOINT_URL: str | None = os.getenv("S3_ENDPOINT_URL")

# Endpoint embedded in pre-signed upload URLs returned to clients.
# Set to http://localhost:4566 when LocalStack runs inside Docker so that
# clients outside the Docker network can still reach it.
PRESIGN_ENDPOINT_URL: str | None = os.getenv("PRESIGN_ENDPOINT_URL") or S3_ENDPOINT_URL

PRESIGN_EXPIRY_SECONDS = int(os.getenv("PRESIGN_EXPIRY_SECONDS", "3600"))

# ── CloudFront (optional) ─────────────────────────────────────────────────────
# When unset the service falls back to S3 pre-signed GET URLs.
# For production, set all three and place the PEM private key at the given path.
CLOUDFRONT_DOMAIN: str | None = os.getenv("CLOUDFRONT_DOMAIN")
CLOUDFRONT_KEY_PAIR_ID: str | None = os.getenv("CLOUDFRONT_KEY_PAIR_ID")
CLOUDFRONT_PRIVATE_KEY_PATH: str | None = os.getenv("CLOUDFRONT_PRIVATE_KEY_PATH")

# ── Database (RDS / local Postgres) ──────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/imagedb",
)
