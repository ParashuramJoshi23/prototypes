import base64

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

# Magic byte signatures
_MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",  # RIFF....WEBP — checked further below
}

MAX_RAW_BYTES = 4_718_592  # ~4.5 MB — accounts for 33% base64 overhead within 6 MB limit


def decode_image_body(event_body: str, is_base64: bool) -> bytes:
    """Decode the Lambda event body to raw bytes."""
    if is_base64:
        return base64.b64decode(event_body)
    return event_body.encode("latin-1") if isinstance(event_body, str) else event_body


def validate_image_bytes(data: bytes) -> str:
    """
    Validate magic bytes and return the detected MIME type.
    Raises ValueError if the content is not a recognised image format.
    """
    if len(data) > MAX_RAW_BYTES:
        raise ValueError(f"Image exceeds maximum allowed size of {MAX_RAW_BYTES} bytes (~4.5 MB)")

    for magic, mime in _MAGIC.items():
        if data[: len(magic)] == magic:
            if mime == "image/webp":
                # RIFF????WEBP — bytes 8-12 must be b"WEBP"
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return mime
                continue
            return mime

    raise ValueError("File content does not match any supported image format (JPEG, PNG, GIF, WebP)")


def validate_metadata(body: dict) -> None:
    """Raise ValueError if required metadata fields are missing or invalid."""
    if not body.get("filename"):
        raise ValueError("'filename' is required")
    filename = body["filename"]
    if not any(filename.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        raise ValueError("'filename' must have a supported image extension")
