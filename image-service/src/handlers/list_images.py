"""GET /images — list images with optional filters."""
import base64
import json
import logging

import boto3.dynamodb.conditions as cond

from utils.aws_clients import DYNAMODB_TABLE, get_dynamodb_resource
from utils.json_encoder import dumps as json_dumps

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json_dumps(body),
    }


def handler(event, context):
    """
    Supported query parameters (all optional, combinable):
      - date_from   : ISO date string YYYY-MM-DD (inclusive)
      - date_to     : ISO date string YYYY-MM-DD (inclusive)
      - tag         : single tag value to filter on
      - content_type: e.g. image/jpeg
      - uploader    : uploader identifier
      - limit       : max items per page (default 50, max 100)
      - last_key    : opaque pagination token (base64 value from previous response's next_key)
    """
    params = event.get("queryStringParameters") or {}
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    tag = params.get("tag")
    content_type_filter = params.get("content_type")
    uploader_filter = params.get("uploader")
    limit = min(int(params.get("limit", 50)), 100)
    last_key_token = params.get("last_key")

    table = get_dynamodb_resource().Table(DYNAMODB_TABLE)

    filter_parts = []

    # --- date range filter ---
    if date_from and date_to:
        filter_parts.append(
            cond.Attr("upload_date").between(date_from, date_to)
        )
    elif date_from:
        filter_parts.append(cond.Attr("upload_date").gte(date_from))
    elif date_to:
        filter_parts.append(cond.Attr("upload_date").lte(date_to))

    # --- tag filter ---
    if tag:
        filter_parts.append(cond.Attr("tags").contains(tag))

    # --- content_type filter ---
    if content_type_filter:
        filter_parts.append(cond.Attr("content_type").eq(content_type_filter))

    # --- uploader filter ---
    if uploader_filter:
        filter_parts.append(cond.Attr("uploader").eq(uploader_filter))

    # Combine all filter expressions with AND
    filter_expr = None
    for part in filter_parts:
        filter_expr = part if filter_expr is None else filter_expr & part

    scan_kwargs = {"Limit": limit}
    if filter_expr is not None:
        scan_kwargs["FilterExpression"] = filter_expr
    if last_key_token:
        try:
            exclusive_start_key = json.loads(base64.b64decode(last_key_token).decode())
            scan_kwargs["ExclusiveStartKey"] = exclusive_start_key
        except Exception:
            return _response(400, {"error": "Invalid pagination token"})

    try:
        result = table.scan(**scan_kwargs)
    except Exception as exc:
        logger.error("DynamoDB scan failed: %s", exc)
        return _response(500, {"error": "Failed to retrieve images"})

    items = result.get("Items", [])
    last_evaluated_key = result.get("LastEvaluatedKey")

    response_body = {
        "images": items,
        "count": len(items),
    }
    if last_evaluated_key:
        # Encode the full key opaquely so we can pass it back as ExclusiveStartKey unchanged
        response_body["next_key"] = base64.b64encode(
            json.dumps(last_evaluated_key).encode()
        ).decode()

    return _response(200, response_body)
