import json
from datetime import datetime, timezone, timedelta

import boto3
import pytest

from conftest import BUCKET, TABLE, REGION, JPEG_B64, PNG_B64, make_upload_event


@pytest.fixture(autouse=True)
def setup(full_aws):
    pass


def call_upload(event):
    from handlers.upload import handler
    return handler(event, {})


def call_list(params=None):
    from handlers.list_images import handler
    event = {"queryStringParameters": params or {}}
    return handler(event, {})


def _seed(full_aws, count=3):
    """Upload several images with varying metadata."""
    from handlers.upload import handler
    ids = []
    for i in range(count):
        body = {
            "filename": f"photo{i}.jpg",
            "image": JPEG_B64,
            "tags": ["tag_a"] if i % 2 == 0 else ["tag_b"],
            "uploader": "alice" if i < 2 else "bob",
        }
        resp = handler({"body": json.dumps(body)}, {})
        ids.append(json.loads(resp["body"])["image_id"])
    return ids


# ─── basic list ───────────────────────────────────────────────────────────────

def test_list_empty(full_aws):
    resp = call_list()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["images"] == []
    assert body["count"] == 0


def test_list_all(full_aws):
    _seed(full_aws)
    resp = call_list()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["count"] == 3


# ─── tag filter ───────────────────────────────────────────────────────────────

def test_list_filter_by_tag_a(full_aws):
    _seed(full_aws)
    resp = call_list({"tag": "tag_a"})
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert all("tag_a" in img["tags"] for img in body["images"])


def test_list_filter_by_tag_b(full_aws):
    _seed(full_aws)
    resp = call_list({"tag": "tag_b"})
    body = json.loads(resp["body"])
    assert all("tag_b" in img["tags"] for img in body["images"])


def test_list_filter_by_nonexistent_tag(full_aws):
    _seed(full_aws)
    resp = call_list({"tag": "does_not_exist"})
    body = json.loads(resp["body"])
    assert body["images"] == []


# ─── uploader filter ──────────────────────────────────────────────────────────

def test_list_filter_by_uploader(full_aws):
    _seed(full_aws)
    resp = call_list({"uploader": "alice"})
    body = json.loads(resp["body"])
    assert all(img["uploader"] == "alice" for img in body["images"])
    assert body["count"] == 2


# ─── date range filter ────────────────────────────────────────────────────────

def test_list_filter_date_from_today(full_aws):
    _seed(full_aws)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    resp = call_list({"date_from": today})
    body = json.loads(resp["body"])
    assert body["count"] == 3  # all uploaded today


def test_list_filter_date_to_yesterday_returns_empty(full_aws):
    _seed(full_aws)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    resp = call_list({"date_to": yesterday})
    body = json.loads(resp["body"])
    assert body["count"] == 0


# ─── combined filters ─────────────────────────────────────────────────────────

def test_list_combined_tag_and_uploader(full_aws):
    _seed(full_aws)
    resp = call_list({"tag": "tag_a", "uploader": "alice"})
    body = json.loads(resp["body"])
    for img in body["images"]:
        assert "tag_a" in img["tags"]
        assert img["uploader"] == "alice"


def test_list_combined_tag_and_date(full_aws):
    _seed(full_aws)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    resp = call_list({"tag": "tag_b", "date_from": today})
    body = json.loads(resp["body"])
    for img in body["images"]:
        assert "tag_b" in img["tags"]


# ─── no queryStringParameters key at all ─────────────────────────────────────

def test_list_no_query_params_key(full_aws):
    from handlers.list_images import handler
    resp = handler({"queryStringParameters": None}, {})
    assert resp["statusCode"] == 200
