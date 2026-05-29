import json
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import ClientError

from conftest import BUCKET, TABLE, REGION, make_upload_event, make_path_event


@pytest.fixture(autouse=True)
def setup(full_aws):
    pass


def call_upload(event):
    from handlers.upload import handler
    return handler(event, {})


def call_delete(image_id: str):
    from handlers.delete_image import handler
    return handler(make_path_event(image_id), {})


def call_get(image_id: str):
    from handlers.get_image import handler
    return handler(make_path_event(image_id), {})


# ─── happy path ───────────────────────────────────────────────────────────────

def test_delete_existing_image_returns_200(full_aws):
    up = json.loads(call_upload(make_upload_event())["body"])
    resp = call_delete(up["image_id"])
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["image_id"] == up["image_id"]


def test_delete_removes_from_dynamodb(full_aws):
    up = json.loads(call_upload(make_upload_event())["body"])
    image_id = up["image_id"]
    call_delete(image_id)

    # Image should no longer be retrievable
    get_resp = call_get(image_id)
    assert get_resp["statusCode"] == 404


def test_delete_removes_from_s3(full_aws):
    up = json.loads(call_upload(make_upload_event())["body"])
    image_id = up["image_id"]
    s3_key = up["metadata"]["s3_key"]
    call_delete(image_id)

    s3 = boto3.client("s3", region_name=REGION)
    with pytest.raises(ClientError) as exc_info:
        s3.get_object(Bucket=BUCKET, Key=s3_key)
    assert exc_info.value.response["Error"]["Code"] == "NoSuchKey"


# ─── not found ────────────────────────────────────────────────────────────────

def test_delete_nonexistent_image_returns_404(full_aws):
    resp = call_delete("00000000-0000-0000-0000-000000000000")
    assert resp["statusCode"] == 404
    assert "not found" in json.loads(resp["body"])["error"]


def test_delete_missing_path_param_returns_400(full_aws):
    from handlers.delete_image import handler
    resp = handler({"pathParameters": {}}, {})
    assert resp["statusCode"] == 400


# ─── partial failure: S3 delete fails ────────────────────────────────────────

def test_delete_s3_failure_still_removes_metadata(full_aws):
    """If S3 delete fails, DynamoDB item should already be gone and we still return 200."""
    up = json.loads(call_upload(make_upload_event())["body"])
    image_id = up["image_id"]

    import utils.aws_clients as aws_clients
    original_get_s3 = aws_clients.get_s3_client

    def broken_s3():
        real_client = original_get_s3()
        real_delete = real_client.delete_object

        def _raise(**kwargs):
            raise ClientError(
                {"Error": {"Code": "InternalError", "Message": "simulated failure"}},
                "delete_object",
            )

        real_client.delete_object = _raise
        return real_client

    with patch.object(aws_clients, "get_s3_client", broken_s3):
        resp = call_delete(image_id)

    # Should still return 200 (metadata removed, S3 cleanup noted in logs)
    assert resp["statusCode"] == 200

    # DynamoDB item should be gone
    dynamo = boto3.resource("dynamodb", region_name=REGION)
    table = dynamo.Table(TABLE)
    item = table.get_item(Key={"image_id": image_id}).get("Item")
    assert item is None


# ─── idempotency ─────────────────────────────────────────────────────────────

def test_delete_twice_second_returns_404(full_aws):
    up = json.loads(call_upload(make_upload_event())["body"])
    image_id = up["image_id"]
    first = call_delete(image_id)
    assert first["statusCode"] == 200
    second = call_delete(image_id)
    assert second["statusCode"] == 404
