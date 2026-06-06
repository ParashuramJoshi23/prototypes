import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    PRESIGN_ENDPOINT_URL,
    PRESIGN_EXPIRY_SECONDS,
    S3_BUCKET,
    S3_ENDPOINT_URL,
)


def _make_client(endpoint_url: str | None):
    kwargs = dict(
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        # SigV4 required for LocalStack and strongly recommended for PUT uploads on real AWS
        config=Config(signature_version="s3v4"),
    )
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def api_client():
    """Client for control-plane calls: create bucket, list, head, get, put."""
    return _make_client(S3_ENDPOINT_URL)


def presign_client():
    """Client whose endpoint is embedded in generated pre-signed URLs.

    PRESIGN_ENDPOINT_URL differs from S3_ENDPOINT_URL when LocalStack runs
    inside Docker Compose: the app reaches it at http://localstack:4566 but
    clients outside Docker need http://localhost:4566.
    """
    return _make_client(PRESIGN_ENDPOINT_URL)


def ensure_bucket() -> None:
    client = api_client()
    try:
        client.head_bucket(Bucket=S3_BUCKET)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            if AWS_REGION == "us-east-1":
                client.create_bucket(Bucket=S3_BUCKET)
            else:
                client.create_bucket(
                    Bucket=S3_BUCKET,
                    CreateBucketConfiguration={"LocationConstraint": AWS_REGION},
                )
        else:
            raise


def generate_upload_url(key: str, content_type: str) -> dict:
    url = presign_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )
    return {"url": url, "key": key, "method": "PUT", "expires_in": PRESIGN_EXPIRY_SECONDS}


def generate_download_url(key: str) -> dict:
    url = presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )
    return {"url": url, "key": key, "expires_in": PRESIGN_EXPIRY_SECONDS}


def download_bytes(key: str) -> bytes:
    return api_client().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    api_client().put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=content_type)
