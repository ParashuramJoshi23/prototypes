import os

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")

S3_BUCKET = os.getenv("S3_BUCKET", "uploads")

# Internal endpoint the app uses to reach S3 / LocalStack (e.g. http://localstack:4566).
# Leave unset when targeting real AWS.
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")

# Endpoint embedded in pre-signed URLs returned to clients.
# Set this when the app connects to LocalStack via a Docker-internal hostname
# that external clients cannot reach (e.g. PRESIGN_ENDPOINT_URL=http://localhost:4566).
# Falls back to S3_ENDPOINT_URL when unset.
PRESIGN_ENDPOINT_URL = os.getenv("PRESIGN_ENDPOINT_URL") or S3_ENDPOINT_URL

PRESIGN_EXPIRY_SECONDS = int(os.getenv("PRESIGN_EXPIRY_SECONDS", "3600"))
