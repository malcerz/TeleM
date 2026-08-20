"""Writable Pillow images mapped directly onto a SharedMemory buffer.

Pillow 12's public ``Image.frombuffer`` path marks RGBA images readonly and
does not expose the supplied writable buffer as the image backing store.  Its
raw decoder has the lower-level ``Image.core.map_buffer`` primitive, which is
used here behind one small adapter.  The returned image owns an ImagingCore
that keeps the exported buffer alive until ``image.close()`` is called.
"""

from __future__ import annotations

from typing import Any

from PIL import Image


def writable_rgba_image(buffer: Any, size: tuple[int, int]) -> Image.Image:
    """Return a writable RGBA Pillow image mapped onto ``buffer``.

    This intentionally uses Pillow's raw mapped-buffer primitive rather than
    ``frombuffer``: on the supported Pillow build, ``frombuffer`` creates a
    readonly RGBA image that does not share the supplied memory.
    """
    width, height = size
    expected = int(width) * int(height) * 4
    if len(buffer) < expected:
        raise ValueError(f"RGBA backing buffer is too small: {len(buffer)} < {expected}")
    if not hasattr(Image.core, "map_buffer"):
        raise RuntimeError("This Pillow build has no writable map_buffer primitive")

    core = Image.core.map_buffer(
        buffer, (int(width), int(height)), "raw", 0, ("RGBA", 0, 1)
    )
    image = Image.Image()
    image.im = core
    image._mode = "RGBA"
    image._size = (int(width), int(height))
    image._readonly = 0
    return image


def close_writable_image(image: Image.Image | None) -> None:
    """Release the Pillow ImagingCore and its exported backing-buffer view."""
    if image is None:
        return
    try:
        image.close()
    except Exception:
        # Pillow close is best-effort here; the caller must still drop its
        # reference before SharedMemory.close().
        try:
            image.im = None
        except Exception:
            pass
