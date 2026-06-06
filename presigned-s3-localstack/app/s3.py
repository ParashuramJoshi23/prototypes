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
        # SigV4 is required for LocalStack and recommended for real AWS PUT uploads
        config=Config(signature_version="s3v4"),
    )
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def api_client():
    """Client for control-plane calls (create bucket, list objects, head)."""
    return _make_client(S3_ENDPOINT_URL)


def presign_client():
    """Client whose endpoint is embedded in generated pre-signed URLs.

    When LocalStack runs inside Docker Compose, PRESIGN_ENDPOINT_URL should be
    http://localhost:4566 so that clients outside Docker can reach it directly,
    while S3_ENDPOINT_URL can stay http://localstack:4566 for internal API calls.
    """
    return _make_client(PRESIGN_ENDPOINT_URL)


def ensure_bucket() -> None:
    client = api_client()
    try:
        client.head_bucket(Bucket=S3_BUCKET)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            # us-east-1 does not accept a LocationConstraint
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
    return {"url": url, "key": key, "method": "GET", "expires_in": PRESIGN_EXPIRY_SECONDS}


def list_objects() -> list[dict]:
    response = api_client().list_objects_v2(Bucket=S3_BUCKET)
    return [
        {
            "key": obj["Key"],
            "size_bytes": obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
        }
        for obj in response.get("Contents", [])
    ]
