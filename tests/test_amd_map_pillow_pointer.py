"""Regression tests for the AMD map Pillow zero-copy upload probe."""

from __future__ import annotations

import ctypes

from PIL import Image

from src.ffmpeg.amd_native_exporter import _pillow_rgba_contiguous_pointer


def test_rgba_pillow_pointer_matches_image_bytes() -> None:
    image = Image.new("RGBA", (7, 5))
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), (x, y, x + y, 255))

    result = _pillow_rgba_contiguous_pointer(image)
    assert result is not None
    ptr, stride = result
    assert stride == image.width * 4
    assert ctypes.string_at(ptr, image.width * image.height * 4) == image.tobytes(
        "raw", "RGBA"
    )


def test_non_rgba_image_uses_safe_fallback() -> None:
    assert _pillow_rgba_contiguous_pointer(Image.new("RGB", (4, 4))) is None
