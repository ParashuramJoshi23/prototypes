"""Shared pytest fixtures — function-scoped to prevent state bleed between tests."""
import base64
import os
import sys

import boto3
import pytest
from moto import mock_aws

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

BUCKET = "test-image-bucket"
TABLE = "test-image-metadata"
REGION = "us-east-1"


def _set_env():
    os.environ["S3_BUCKET"] = BUCKET
    os.environ["DYNAMODB_TABLE"] = TABLE
    os.environ["AWS_REGION"] = REGION
    os.environ["USE_LOCALSTACK"] = "false"
    os.environ["AWS_DEFAULT_REGION"] = REGION
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"


@pytest.fixture()
def aws_env(monkeypatch):
    """Set AWS env vars before each test."""
    _set_env()


@pytest.fixture()
def s3_bucket(aws_env):
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture()
def dynamo_table(aws_env):
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        table = resource.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "image_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "image_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName=TABLE)
        yield table


@pytest.fixture()
def full_aws(aws_env):
    """Combined S3 + DynamoDB mock — single mock_aws context."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        dynamo = boto3.resource("dynamodb", region_name=REGION)
        table = dynamo.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "image_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "image_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName=TABLE)
        yield {"s3": s3, "table": table}


# ---- Minimal valid image bytes ----

# 1×1 white JPEG
JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),\x01\x00"  # truncated but magic bytes valid
)
# 8-byte PNG header
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

JPEG_B64 = base64.b64encode(JPEG_BYTES).decode()
PNG_B64 = base64.b64encode(PNG_BYTES).decode()


def make_upload_event(filename="photo.jpg", image_b64=None, extra=None):
    body = {
        "filename": filename,
        "image": image_b64 or JPEG_B64,
        "tags": ["nature", "sunset"],
        "description": "A beautiful sunset",
        "uploader": "user@example.com",
    }
    if extra:
        body.update(extra)
    import json
    return {"body": json.dumps(body)}


def make_path_event(image_id: str) -> dict:
    return {"pathParameters": {"image_id": image_id}}
