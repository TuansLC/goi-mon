"""Menu photo processing (Pillow).

Chủ quán chụp ảnh bằng điện thoại thì file thường 3–5 MB và có EXIF orientation.
Ảnh gốc không được đưa thẳng lên storage: khách ngồi quán dùng 4G, một menu 40
món sẽ tốn hàng trăm MB. Mỗi ảnh vì vậy được chuẩn hoá thành 2 biến thể WebP:

- ``thumb``: 400×400, cắt giữa (center-crop) — dùng cho danh sách menu.
- ``large``: cạnh dài tối đa 1000px, giữ tỉ lệ — dùng cho lightbox.

Hàm ở đây là **đồng bộ** và CPU-bound, nên router phải gọi qua
``asyncio.to_thread`` để không chặn event loop.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

# Upload limits / accepted formats.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

THUMB_SIZE = (400, 400)
LARGE_MAX_SIDE = 1000
THUMB_QUALITY = 80
LARGE_QUALITY = 82

# Menu photos are written under a versioned key, so they can be cached forever.
IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"
IMAGE_CONTENT_TYPE = "image/webp"


class ImageValidationError(ValueError):
    """Raised when the uploaded bytes are not a usable image."""


def _load_flattened(raw: bytes) -> Image.Image:
    """Decode bytes into an RGB image with EXIF rotation already applied.

    Transparent images are flattened onto white so WebP output never shows a
    black background.
    """
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # Pillow raises a variety of errors here.
        raise ImageValidationError(
            "Tệp không phải ảnh hợp lệ hoặc đã bị lỗi."
        ) from exc

    # Phone photos carry an orientation tag; without this they appear sideways.
    img = ImageOps.exif_transpose(img)

    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGB", img.size, (255, 255, 255))
        canvas.paste(img, mask=img.split()[-1])
        return canvas

    return img.convert("RGB")


def _encode_webp(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def process_menu_image(raw: bytes) -> tuple[bytes, bytes]:
    """Return ``(thumb_webp, large_webp)`` for an uploaded menu photo.

    Raises:
        ImageValidationError: the bytes could not be decoded as an image.
    """
    base = _load_flattened(raw)

    # Center-crop to a square so every row in the menu list lines up.
    thumb = ImageOps.fit(base, THUMB_SIZE, method=Image.LANCZOS, centering=(0.5, 0.5))

    large = base.copy()
    large.thumbnail((LARGE_MAX_SIDE, LARGE_MAX_SIDE), Image.LANCZOS)

    return _encode_webp(thumb, THUMB_QUALITY), _encode_webp(large, LARGE_QUALITY)
