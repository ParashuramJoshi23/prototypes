"""DELETE /images/{image_id} — delete image from S3 and metadata from DynamoDB."""
import json
import logging

from utils.aws_clients import S3_BUCKET, DYNAMODB_TABLE, get_s3_client, get_dynamodb_resource

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
    Path parameter: image_id
    Delete order: DynamoDB first (so no new presigned URLs can be generated),
    then S3.  If S3 deletion fails the item is already gone from the index;
    an S3 lifecycle policy should clean up orphaned objects as a safety net.
    """
    path_params = event.get("pathParameters") or {}
    image_id = path_params.get("image_id")
    if not image_id:
        return _response(400, {"error": "Missing path parameter: image_id"})

    table = get_dynamodb_resource().Table(DYNAMODB_TABLE)

    # --- fetch metadata so we know the S3 key ---
    try:
        result = table.get_item(Key={"image_id": image_id})
    except Exception as exc:
        logger.error("DynamoDB get_item failed: %s", exc)
        return _response(500, {"error": "Failed to look up image"})

    item = result.get("Item")
    if not item:
        return _response(404, {"error": f"Image '{image_id}' not found"})

    s3_key = item["s3_key"]

    # --- delete metadata first ---
    try:
        table.delete_item(Key={"image_id": image_id})
    except Exception as exc:
        logger.error("DynamoDB delete_item failed for image_id=%s: %s", image_id, exc)
        return _response(500, {"error": "Failed to delete image metadata"})

    # --- delete from S3 ---
    s3 = get_s3_client()
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
    except Exception as exc:
        # Metadata already deleted; log for manual / lifecycle cleanup
        logger.error(
            "S3 delete_object failed for key=%s (metadata already removed). "
            "Orphaned object requires manual cleanup. Error: %s",
            s3_key,
            exc,
        )
        # Still return 200 — the image is no longer discoverable via the API
        return _response(
            200,
            {
                "message": "Image metadata deleted; S3 object removal failed and may require cleanup",
                "image_id": image_id,
            },
        )

    logger.info("Deleted image_id=%s s3_key=%s", image_id, s3_key)
    return _response(200, {"message": "Image deleted successfully", "image_id": image_id})
