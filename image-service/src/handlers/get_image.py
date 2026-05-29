"""GET /images/{image_id} — retrieve image metadata and a presigned download URL."""
import logging

from utils.aws_clients import S3_BUCKET, DYNAMODB_TABLE, get_s3_client, get_dynamodb_resource
from utils.json_encoder import dumps as json_dumps

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PRESIGNED_URL_EXPIRY = 3600  # seconds


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json_dumps(body),
    }


def handler(event, context):
    """
    Path parameter: image_id
    Returns image metadata + a presigned S3 URL valid for 1 hour.
    """
    path_params = event.get("pathParameters") or {}
    image_id = path_params.get("image_id")
    if not image_id:
        return _response(400, {"error": "Missing path parameter: image_id"})

    # --- fetch metadata from DynamoDB ---
    table = get_dynamodb_resource().Table(DYNAMODB_TABLE)
    try:
        result = table.get_item(Key={"image_id": image_id})
    except Exception as exc:
        logger.error("DynamoDB get_item failed: %s", exc)
        return _response(500, {"error": "Failed to retrieve image metadata"})

    item = result.get("Item")
    if not item:
        return _response(404, {"error": f"Image '{image_id}' not found"})

    # --- generate presigned URL ---
    s3 = get_s3_client()
    try:
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": item["s3_key"]},
            ExpiresIn=PRESIGNED_URL_EXPIRY,
        )
    except Exception as exc:
        logger.error("Failed to generate presigned URL: %s", exc)
        return _response(500, {"error": "Failed to generate download URL"})

    return _response(
        200,
        {
            "metadata": item,
            "download_url": presigned_url,
            "url_expires_in_seconds": PRESIGNED_URL_EXPIRY,
        },
    )
