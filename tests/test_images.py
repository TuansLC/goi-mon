"""Unit tests for menu photo processing (qorder_api.images)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from qorder_api.images import (
    LARGE_MAX_SIDE,
    THUMB_SIZE,
    ImageValidationError,
    process_menu_image,
)


def _encode(img: Image.Image, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _open(raw: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw))
    img.load()
    return img


class TestProcessMenuImage:
    def test_rejects_non_image_bytes(self):
        with pytest.raises(ImageValidationError):
            process_menu_image(b"this is definitely not an image")

    def test_outputs_are_webp(self):
        raw = _encode(Image.new("RGB", (800, 600), (200, 120, 40)))

        thumb, large = process_menu_image(raw)

        assert _open(thumb).format == "WEBP"
        assert _open(large).format == "WEBP"

    def test_thumb_is_square_and_fixed_size(self):
        """A 3:2 photo still yields a square thumb so menu rows line up."""
        raw = _encode(Image.new("RGB", (900, 600), (10, 200, 90)))

        thumb, _ = process_menu_image(raw)

        assert _open(thumb).size == THUMB_SIZE

    def test_large_is_capped_on_the_long_side_and_keeps_ratio(self):
        raw = _encode(Image.new("RGB", (2400, 1200), (30, 60, 90)))

        _, large = process_menu_image(raw)
        width, height = _open(large).size

        assert max(width, height) == LARGE_MAX_SIDE
        assert width == pytest.approx(height * 2, abs=1)  # 2:1 preserved

    def test_small_image_is_not_upscaled(self):
        raw = _encode(Image.new("RGB", (320, 240), (128, 128, 128)))

        _, large = process_menu_image(raw)

        assert _open(large).size == (320, 240)

    def test_transparent_png_is_flattened_onto_white(self):
        """WebP keeps alpha, so an unflattened PNG would show black in the UI."""
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        raw = _encode(img, fmt="PNG")

        thumb, _ = process_menu_image(raw)
        result = _open(thumb)

        assert result.mode in ("RGB", "RGBX")
        # Fully transparent input must come out white, not black.
        assert result.convert("RGB").getpixel((5, 5)) == (255, 255, 255)

    def test_exif_orientation_is_applied(self):
        """Phone photos carry an orientation tag; ignoring it renders sideways."""
        portrait = Image.new("RGB", (400, 800), (200, 30, 30))
        exif = portrait.getexif()
        exif[274] = 6  # Orientation: rotate 90° CW
        buf = io.BytesIO()
        portrait.save(buf, format="JPEG", exif=exif)

        _, large = process_menu_image(buf.getvalue())
        width, height = _open(large).size

        # After transposing, the stored portrait becomes landscape.
        assert width > height
