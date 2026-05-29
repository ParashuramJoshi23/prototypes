# Image Service

A serverless image upload and storage service built with Python, AWS Lambda, API Gateway, S3, and DynamoDB. Designed for local development with [LocalStack](https://localstack.cloud/).

## Architecture

```
Client → API Gateway → Lambda (handler) → S3  (image blobs)
                                        → DynamoDB (metadata)
```

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/images` | `upload.handler` | Upload image with metadata |
| GET | `/images` | `list_images.handler` | List images (filterable) |
| GET | `/images/{image_id}` | `get_image.handler` | Get metadata + presigned URL |
| DELETE | `/images/{image_id}` | `delete_image.handler` | Delete image |

## Prerequisites

- Python 3.7+
- Docker + Docker Compose (for LocalStack)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) (optional, for local Lambda invocation)

## Local Development with LocalStack

### 1. Start LocalStack

```bash
docker-compose up -d
```

### 2. Bootstrap infrastructure

```bash
pip install awscli-local  # thin wrapper that points to localhost:4566

# Create S3 bucket
awslocal s3 mb s3://image-service-bucket

# Create DynamoDB table
awslocal dynamodb create-table \
  --table-name image-service-metadata \
  --attribute-definitions AttributeName=image_id,AttributeType=S \
  --key-schema AttributeName=image_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Deploy with SAM
USE_LOCALSTACK=true sam build && sam deploy --guided
```

### 3. Set environment variables

```bash
export USE_LOCALSTACK=true
export LOCALSTACK_ENDPOINT=http://localhost:4566
export S3_BUCKET=image-service-bucket
export DYNAMODB_TABLE=image-service-metadata
export AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
```

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests use `moto` to mock S3 and DynamoDB — no Docker required.

---

## API Reference

### POST /images — Upload image

Upload a base64-encoded image with metadata.

**Request body (JSON):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `filename` | string | ✅ | Must have a supported extension (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`) |
| `image` | string | ✅ | Base64-encoded image bytes |
| `description` | string | ❌ | Free-text description |
| `tags` | string[] | ❌ | List of searchable tags |
| `uploader` | string | ❌ | Uploader identifier (default: `anonymous`) |

**Constraints:**
- Max raw image size: **~4.5 MB** (accounts for 6 MB API Gateway limit after base64 overhead)
- Supported formats: JPEG, PNG, GIF, WebP (validated by magic bytes, not just extension)

**Response 201:**
```json
{
  "image_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Image uploaded successfully",
  "metadata": {
    "image_id": "550e8400-e29b-41d4-a716-446655440000",
    "filename": "sunset.jpg",
    "s3_key": "images/550e8400.../sunset.jpg",
    "content_type": "image/jpeg",
    "size_bytes": 204800,
    "upload_timestamp": "2024-01-15T10:30:00+00:00",
    "upload_date": "2024-01-15",
    "tags": ["nature", "sunset"],
    "description": "Golden hour at the beach",
    "uploader": "alice@example.com"
  }
}
```

**curl example:**
```bash
IMAGE_B64=$(base64 -w0 photo.jpg)
curl -X POST https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/images \
  -H "Content-Type: application/json" \
  -d "{
    \"filename\": \"photo.jpg\",
    \"image\": \"$IMAGE_B64\",
    \"tags\": [\"nature\", \"sunset\"],
    \"description\": \"Golden hour\",
    \"uploader\": \"alice@example.com\"
  }"
```

---

### GET /images — List images

List images with optional filters. All parameters are combinable.

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tag` | string | Filter to images containing this tag |
| `uploader` | string | Filter by uploader identifier |
| `date_from` | string | Inclusive start date `YYYY-MM-DD` |
| `date_to` | string | Inclusive end date `YYYY-MM-DD` |
| `content_type` | string | Filter by MIME type (e.g. `image/png`) |
| `limit` | integer | Max results per page (default 50, max 100) |
| `last_key` | string | Pagination token (`image_id`) from previous response |

**Response 200:**
```json
{
  "images": [ { "image_id": "...", "filename": "...", ... } ],
  "count": 12,
  "next_key": "550e8400-..."   // present only when more pages exist
}
```

**curl examples:**
```bash
BASE_URL="https://<api-id>.execute-api.us-east-1.amazonaws.com/prod"

# List all
curl "$BASE_URL/images"

# Filter by tag
curl "$BASE_URL/images?tag=sunset"

# Filter by uploader
curl "$BASE_URL/images?uploader=alice@example.com"

# Date range
curl "$BASE_URL/images?date_from=2024-01-01&date_to=2024-01-31"

# Combined: tag + date range
curl "$BASE_URL/images?tag=nature&date_from=2024-01-01"

# Pagination
curl "$BASE_URL/images?limit=10"
# Use next_key from response for next page:
curl "$BASE_URL/images?limit=10&last_key=<next_key>"
```

---

### GET /images/{image_id} — Get image

Returns image metadata and a presigned S3 URL for downloading.

**Response 200:**
```json
{
  "metadata": { "image_id": "...", "filename": "...", ... },
  "download_url": "https://s3.amazonaws.com/image-service-bucket/images/.../photo.jpg?X-Amz-...",
  "url_expires_in_seconds": 3600
}
```

**Response 404:**
```json
{ "error": "Image '550e8400-...' not found" }
```

**curl example:**
```bash
curl "$BASE_URL/images/550e8400-e29b-41d4-a716-446655440000"
# Then download the image:
curl -o downloaded.jpg "$(curl -s "$BASE_URL/images/<id>" | jq -r '.download_url')"
```

---

### DELETE /images/{image_id} — Delete image

Removes image metadata from DynamoDB first, then deletes the object from S3.

**Response 200:**
```json
{ "message": "Image deleted successfully", "image_id": "550e8400-..." }
```

**Response 404:**
```json
{ "error": "Image '550e8400-...' not found" }
```

**curl example:**
```bash
curl -X DELETE "$BASE_URL/images/550e8400-e29b-41d4-a716-446655440000"
```

---

## Deployment (AWS)

```bash
sam build
sam deploy --guided
# Follow prompts — the API URL is printed in Outputs
```

## Project Structure

```
image-service/
├── src/
│   ├── handlers/
│   │   ├── upload.py        # POST /images
│   │   ├── list_images.py   # GET /images
│   │   ├── get_image.py     # GET /images/{image_id}
│   │   └── delete_image.py  # DELETE /images/{image_id}
│   └── utils/
│       ├── aws_clients.py   # boto3 client factories
│       ├── validators.py    # magic-bytes + field validation
│       └── json_encoder.py  # Decimal-safe JSON encoder
├── tests/
│   ├── conftest.py          # moto fixtures (function-scoped)
│   ├── test_upload.py
│   ├── test_list_images.py
│   ├── test_get_image.py
│   └── test_delete_image.py
├── template.yaml            # SAM / CloudFormation IaC
├── docker-compose.yml       # LocalStack
├── requirements.txt
├── requirements-dev.txt
└── setup.cfg
```

## Design Notes

- **Magic-bytes validation**: uploaded bytes are inspected (not just the filename/Content-Type) before writing to S3, preventing arbitrary file uploads.
- **Delete ordering**: DynamoDB item is removed first, so no new presigned URLs can be generated for a deleted image. If S3 deletion then fails, the object is orphaned but not discoverable; an S3 lifecycle rule on the `images/` prefix provides a safety net.
- **Pagination**: the list endpoint accepts a `last_key` token and respects DynamoDB's `LastEvaluatedKey` to handle tables larger than a single 1 MB scan page.
- **Decimal serialization**: DynamoDB returns numeric values as `decimal.Decimal`; all responses pass through `DecimalEncoder` to produce standard JSON integers/floats.
