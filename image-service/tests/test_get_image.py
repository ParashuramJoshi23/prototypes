import json

import pytest

from conftest import JPEG_B64, JPEG_BYTES, make_upload_event, make_path_event


@pytest.fixture(autouse=True)
def setup(full_aws):
    pass


def call_upload(event):
    from handlers.upload import handler
    return handler(event, {})


def call_get(image_id: str):
    from handlers.get_image import handler
    return handler(make_path_event(image_id), {})


# ─── happy path ───────────────────────────────────────────────────────────────

def test_get_existing_image_returns_200(full_aws):
    up = json.loads(call_upload(make_upload_event())["body"])
    image_id = up["image_id"]

    resp = call_get(image_id)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["metadata"]["image_id"] == image_id
    assert body["metadata"]["filename"] == "photo.jpg"


def test_get_returns_presigned_url(full_aws):
    up = json.loads(call_upload(make_upload_event())["body"])
    resp = call_get(up["image_id"])
    body = json.loads(resp["body"])
    assert "download_url" in body
    # Presigned URL contains the bucket and key
    assert "photo.jpg" in body["download_url"] or up["image_id"] in body["download_url"]


def test_get_returns_url_expiry(full_aws):
    up = json.loads(call_upload(make_upload_event())["body"])
    resp = call_get(up["image_id"])
    body = json.loads(resp["body"])
    assert body["url_expires_in_seconds"] == 3600


def test_get_metadata_includes_all_fields(full_aws):
    up = json.loads(call_upload(make_upload_event())["body"])
    resp = call_get(up["image_id"])
    meta = json.loads(resp["body"])["metadata"]
    for field in ("image_id", "filename", "s3_key", "content_type", "size_bytes",
                  "upload_timestamp", "tags", "description", "uploader"):
        assert field in meta, f"Missing field: {field}"


# ─── not found / bad input ────────────────────────────────────────────────────

def test_get_nonexistent_image_returns_404(full_aws):
    resp = call_get("00000000-0000-0000-0000-000000000000")
    assert resp["statusCode"] == 404
    assert "not found" in json.loads(resp["body"])["error"]


def test_get_missing_path_param_returns_400(full_aws):
    from handlers.get_image import handler
    resp = handler({"pathParameters": {}}, {})
    assert resp["statusCode"] == 400


def test_get_null_path_params_returns_400(full_aws):
    from handlers.get_image import handler
    resp = handler({"pathParameters": None}, {})
    assert resp["statusCode"] == 400
