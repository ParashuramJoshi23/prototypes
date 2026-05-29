import base64
import json

import boto3
import pytest
from moto import mock_aws

from conftest import BUCKET, TABLE, REGION, JPEG_B64, PNG_B64, JPEG_BYTES, PNG_BYTES, make_upload_event


@pytest.fixture(autouse=True)
def setup(full_aws):
    pass


def call_upload(event):
    from handlers.upload import handler
    return handler(event, {})


# ─── happy path ───────────────────────────────────────────────────────────────

def test_upload_jpeg_success(full_aws):
    resp = call_upload(make_upload_event())
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert "image_id" in body
    assert body["metadata"]["filename"] == "photo.jpg"
    assert body["metadata"]["content_type"] == "image/jpeg"
    assert body["metadata"]["uploader"] == "user@example.com"
    assert "nature" in body["metadata"]["tags"]


def test_upload_png_success(full_aws):
    resp = call_upload(make_upload_event(filename="image.png", image_b64=PNG_B64))
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["metadata"]["content_type"] == "image/png"


def test_upload_stores_in_s3(full_aws):
    resp = call_upload(make_upload_event())
    body = json.loads(resp["body"])
    image_id = body["image_id"]
    s3_key = body["metadata"]["s3_key"]

    s3 = boto3.client("s3", region_name=REGION)
    obj = s3.get_object(Bucket=BUCKET, Key=s3_key)
    assert obj["Body"].read() == JPEG_BYTES


def test_upload_stores_metadata_in_dynamodb(full_aws):
    resp = call_upload(make_upload_event())
    body = json.loads(resp["body"])
    image_id = body["image_id"]

    dynamo = boto3.resource("dynamodb", region_name=REGION)
    table = dynamo.Table(TABLE)
    item = table.get_item(Key={"image_id": image_id})["Item"]
    assert item["filename"] == "photo.jpg"
    assert item["size_bytes"] == len(JPEG_BYTES)


# ─── missing / invalid fields ─────────────────────────────────────────────────

def test_upload_missing_filename(full_aws):
    event = {"body": json.dumps({"image": JPEG_B64})}
    resp = call_upload(event)
    assert resp["statusCode"] == 400
    assert "filename" in json.loads(resp["body"])["error"]


def test_upload_missing_image(full_aws):
    event = {"body": json.dumps({"filename": "photo.jpg"})}
    resp = call_upload(event)
    assert resp["statusCode"] == 400
    assert "image" in json.loads(resp["body"])["error"]


def test_upload_invalid_json_body(full_aws):
    resp = call_upload({"body": "not-json"})
    assert resp["statusCode"] == 400


def test_upload_invalid_extension(full_aws):
    resp = call_upload(make_upload_event(filename="document.pdf"))
    assert resp["statusCode"] == 400
    assert "extension" in json.loads(resp["body"])["error"]


def test_upload_bad_magic_bytes(full_aws):
    # Valid base64 but content is not an image
    fake = base64.b64encode(b"PK\x03\x04" + b"\x00" * 50).decode()  # ZIP magic
    resp = call_upload(make_upload_event(filename="photo.jpg", image_b64=fake))
    assert resp["statusCode"] == 400
    assert "image format" in json.loads(resp["body"])["error"]


def test_upload_oversized_image(full_aws):
    big = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024)).decode()
    resp = call_upload(make_upload_event(filename="big.jpg", image_b64=big))
    assert resp["statusCode"] == 400
    assert "size" in json.loads(resp["body"])["error"]
