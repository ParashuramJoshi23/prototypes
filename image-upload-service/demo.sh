#!/usr/bin/env bash
# End-to-end demo: create user → upload public photo → upload private photo
# Usage: bash demo.sh [photo.jpg]
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

# ── Create a test image if none provided ─────────────────────────────────────
PHOTO_FILE="${1:-/tmp/demo_photo.jpg}"
if [[ ! -f "$PHOTO_FILE" ]]; then
    python3 - "$PHOTO_FILE" <<'PY'
import sys
from PIL import Image, ImageDraw
path = sys.argv[1]
img = Image.new("RGB", (640, 480), (70, 130, 180))
d = ImageDraw.Draw(img)
d.rectangle([20, 20, 620, 460], outline=(255, 255, 255), width=4)
d.text((180, 220), "Demo Photo", fill=(255, 255, 255))
img.save(path)
print(f"Created test image: {path}")
PY
fi

sep() { echo ""; echo "══ $* ══"; }

# ── 1. Create a user ──────────────────────────────────────────────────────────
sep "1. Create user"
USER=$(curl -sf -X POST "$BASE_URL/users" \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","username":"demo"}')
echo "$USER" | python3 -m json.tool
USER_ID=$(echo "$USER" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# ── 2. Upload a PUBLIC photo ──────────────────────────────────────────────────
sep "2a. Request pre-signed upload URL (public)"
PUB=$(curl -sf -X POST "$BASE_URL/photos/upload-url" \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"$USER_ID\",\"filename\":\"demo.jpg\",\"content_type\":\"image/jpeg\",\"is_private\":false}")
echo "$PUB" | python3 -m json.tool

PUB_URL=$(echo "$PUB"      | python3 -c "import sys,json; print(json.load(sys.stdin)['upload_url'])")
PUB_ID=$(echo "$PUB"       | python3 -c "import sys,json; print(json.load(sys.stdin)['photo_id'])")

sep "2b. Upload public photo directly to S3"
curl -sf -X PUT "$PUB_URL" -H "Content-Type: image/jpeg" --data-binary "@$PHOTO_FILE"
echo "Upload complete."

sep "2c. Confirm public upload"
curl -sf -X POST "$BASE_URL/photos/$PUB_ID/confirm" | python3 -m json.tool

sep "2d. Get view URL for public photo"
curl -sf "$BASE_URL/photos/$PUB_ID/view" | python3 -m json.tool

# ── 3. Upload a PRIVATE photo (watermark applied) ─────────────────────────────
sep "3a. Request pre-signed upload URL (private)"
PRV=$(curl -sf -X POST "$BASE_URL/photos/upload-url" \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"$USER_ID\",\"filename\":\"private.jpg\",\"content_type\":\"image/jpeg\",\"is_private\":true}")
echo "$PRV" | python3 -m json.tool

PRV_URL=$(echo "$PRV" | python3 -c "import sys,json; print(json.load(sys.stdin)['upload_url'])")
PRV_ID=$(echo "$PRV"  | python3 -c "import sys,json; print(json.load(sys.stdin)['photo_id'])")

sep "3b. Upload private photo directly to S3"
curl -sf -X PUT "$PRV_URL" -H "Content-Type: image/jpeg" --data-binary "@$PHOTO_FILE"
echo "Upload complete."

sep "3c. Confirm private upload (watermark is applied here)"
curl -sf -X POST "$BASE_URL/photos/$PRV_ID/confirm" | python3 -m json.tool

sep "3d. Get view URL for private photo (watermarked copy)"
VIEW=$(curl -sf "$BASE_URL/photos/$PRV_ID/view")
echo "$VIEW" | python3 -m json.tool

DOWNLOAD_URL=$(echo "$VIEW" | python3 -c "import sys,json; print(json.load(sys.stdin)['url'])")
sep "3e. Download watermarked photo"
curl -sf "$DOWNLOAD_URL" -o /tmp/watermarked_result.jpg
echo "Saved watermarked photo to /tmp/watermarked_result.jpg"

# ── 4. List user's photos ─────────────────────────────────────────────────────
sep "4. List all photos for user"
curl -sf "$BASE_URL/users/$USER_ID/photos" | python3 -m json.tool

echo ""
echo "Done."
