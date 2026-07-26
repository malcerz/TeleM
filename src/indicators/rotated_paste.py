"""Rotated paste utility — composite rotated overlays onto a base image.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore


def rotated_paste(
    base_img: Image.Image,
    overlay: Image.Image,
    center_x: int,
    center_y: int,
    rotation: int,
) -> None:
    """Paste *overlay* onto *base_img* centred at (center_x, center_y) with rotation.
    Modifies base_img in place."""
    rotation = int(rotation) % 360
    if rotation == 90:
        overlay = overlay.transpose(Image.Transpose.ROTATE_90)
    elif rotation == 180:
        overlay = overlay.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        overlay = overlay.transpose(Image.Transpose.ROTATE_270)
    x = int(round(center_x - overlay.width / 2))
    y = int(round(center_y - overlay.height / 2))
    base_img.alpha_composite(overlay, (x, y))
