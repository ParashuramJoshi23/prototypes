"""POST /images — upload an image with metadata."""
import json
import logging
import uuid
from datetime import datetime, timezone

from utils.aws_clients import S3_BUCKET, DYNAMODB_TABLE, get_s3_client, get_dynamodb_resource
from utils.validators import decode_image_body, validate_image_bytes, validate_metadata

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    """
    Expects multipart-style JSON envelope:
    {
      "filename": "photo.jpg",
      "description": "optional",
      "tags": ["tag1", "tag2"],        # optional
      "uploader": "user@example.com",  # optional
      "image": "<base64-encoded bytes>"
    }
    or a raw binary body with isBase64Encoded=true and query params for metadata.
    For simplicity this handler accepts a JSON body with an "image" field (base64).
    """
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Request body must be valid JSON"})

    if not isinstance(body, dict):
        return _response(400, {"error": "Request body must be a JSON object"})

    # --- validate metadata ---
    try:
        validate_metadata(body)
    except ValueError as exc:
        return _response(400, {"error": str(exc)})

    # --- decode + validate image bytes ---
    image_b64 = body.get("image")
    if not image_b64:
        return _response(400, {"error": "'image' field (base64-encoded image data) is required"})

    try:
        image_bytes = decode_image_body(image_b64, is_base64=True)
    except Exception as exc:
        return _response(400, {"error": f"Failed to decode image data: {exc}"})

    try:
        detected_mime = validate_image_bytes(image_bytes)
    except ValueError as exc:
        return _response(400, {"error": str(exc)})

    # --- build metadata ---
    image_id = str(uuid.uuid4())
    filename = body["filename"]
    now = datetime.now(timezone.utc)
    upload_timestamp = now.isoformat()
    upload_date = now.strftime("%Y-%m-%d")
    tags = body.get("tags", [])
    description = body.get("description", "")
    uploader = body.get("uploader", "anonymous")
    s3_key = f"images/{image_id}/{filename}"

    # --- write to S3 ---
    s3 = get_s3_client()
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=image_bytes,
            ContentType=detected_mime,
        )
    except Exception as exc:
        logger.error("S3 put_object failed: %s", exc)
        return _response(500, {"error": "Failed to store image"})

    # --- write metadata to DynamoDB ---
    table = get_dynamodb_resource().Table(DYNAMODB_TABLE)
    item = {
        "image_id": image_id,
        "filename": filename,
        "s3_key": s3_key,
        "content_type": detected_mime,
        "size_bytes": len(image_bytes),
        "upload_timestamp": upload_timestamp,
        "upload_date": upload_date,
        "tags": tags,
        "description": description,
        "uploader": uploader,
    }
    try:
        table.put_item(Item=item)
    except Exception as exc:
        logger.error("DynamoDB put_item failed: %s — rolling back S3 object", exc)
        # Best-effort rollback: remove orphaned S3 object
        try:
            s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        except Exception:
            pass
        return _response(500, {"error": "Failed to store image metadata"})

    logger.info("Uploaded image_id=%s filename=%s size=%d", image_id, filename, len(image_bytes))
    return _response(201, {"image_id": image_id, "message": "Image uploaded successfully", "metadata": item})
