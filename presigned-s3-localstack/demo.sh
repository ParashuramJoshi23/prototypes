#!/usr/bin/env bash
# End-to-end demo: request pre-signed URL → upload → download → list
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
FILENAME="${1:-hello.txt}"
CONTENT="Hello from pre-signed upload at $(date)!"

echo "====== 1. Request pre-signed upload URL ======"
UPLOAD_RESP=$(curl -sf -X POST "$BASE_URL/presign/upload" \
  -H "Content-Type: application/json" \
  -d "{\"filename\": \"$FILENAME\", \"content_type\": \"text/plain\"}")
echo "$UPLOAD_RESP" | python3 -m json.tool

UPLOAD_URL=$(echo "$UPLOAD_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['url'])")
KEY=$(echo "$UPLOAD_RESP"         | python3 -c "import sys,json; print(json.load(sys.stdin)['key'])")

echo ""
echo "====== 2. Upload directly to S3 via pre-signed URL ======"
curl -sf -X PUT "$UPLOAD_URL" \
  -H "Content-Type: text/plain" \
  --data-binary "$CONTENT"
echo "Upload complete."

echo ""
echo "====== 3. Request pre-signed download URL ======"
DOWNLOAD_RESP=$(curl -sf "$BASE_URL/presign/download/$KEY")
echo "$DOWNLOAD_RESP" | python3 -m json.tool

DOWNLOAD_URL=$(echo "$DOWNLOAD_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['url'])")

echo ""
echo "====== 4. Download via pre-signed URL ======"
curl -sf "$DOWNLOAD_URL"
echo ""

echo ""
echo "====== 5. List bucket contents ======"
curl -sf "$BASE_URL/files" | python3 -m json.tool
