import boto3
from botocore.config import Config

from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    PRESIGN_ENDPOINT_URL,
    PRESIGN_EXPIRY_SECONDS,
    S3_BUCKET,
    S3_ENDPOINT_URL,
)


def _client(endpoint_url=None):
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        endpoint_url=endpoint_url,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket() -> None:
    client = _client(S3_ENDPOINT_URL)
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    if S3_BUCKET not in existing:
        client.create_bucket(Bucket=S3_BUCKET)


def generate_upload_url(s3_key: str, content_type: str) -> dict:
    """
    Return a pre-signed PUT URL the client uses to upload media directly to S3.

    Two-endpoint design:
    - S3_ENDPOINT_URL   : docker-internal address the app uses to talk to S3.
    - PRESIGN_ENDPOINT_URL : address embedded in the URL given to the client.
      Must be reachable from outside the Docker network (e.g. localhost:4566).

    This split is needed because the internal hostname (e.g. "localstack") is
    not routable from the client's machine.
    """
    client = _client(PRESIGN_ENDPOINT_URL)
    url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )
    return {"url": url, "expires_in": PRESIGN_EXPIRY_SECONDS}


def generate_download_url(s3_key: str) -> dict:
    """Return a pre-signed GET URL for viewing media."""
    client = _client(PRESIGN_ENDPOINT_URL)
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": s3_key},
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )
    return {"url": url, "expires_in": PRESIGN_EXPIRY_SECONDS}
