"""Image processing: watermark application for private photos."""

import io

from PIL import Image, ImageDraw, ImageFont

from app import s3

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def _apply_watermark(data: bytes, text: str = "PRIVATE") -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    w, h = img.size

    font = _load_font(max(24, w // 8))

    # Draw repeated text on an oversized transparent layer, then rotate 30°
    # so the watermark tiles diagonally across the image.
    layer_size = max(w, h) * 2
    layer = Image.new("RGBA", (layer_size, layer_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    step_x = layer_size // 4
    step_y = layer_size // 6
    for xi in range(0, layer_size, step_x):
        for yi in range(0, layer_size, step_y):
            draw.text((xi, yi), text, font=font, fill=(255, 255, 255, 70))

    rotated = layer.rotate(30, expand=False)
    # Crop to match original image dimensions
    cx = (layer_size - w) // 2
    cy = (layer_size - h) // 2
    overlay = rotated.crop((cx, cy, cx + w, cy + h))

    watermarked = Image.alpha_composite(img, overlay).convert("RGB")

    buf = io.BytesIO()
    watermarked.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def process_private_photo(photo_id: str, s3_key: str) -> str:
    """Download original, watermark it, re-upload, return new S3 key."""
    original = s3.download_bytes(s3_key)
    watermarked = _apply_watermark(original)
    processed_key = f"photos/{photo_id}/watermarked.jpg"
    s3.upload_bytes(processed_key, watermarked, "image/jpeg")
    return processed_key
