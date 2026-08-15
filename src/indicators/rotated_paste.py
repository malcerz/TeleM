"""Rotated paste utility — composite rotated overlays onto a base image.

Extracted from ``overlay_renderer.py``.

ETAP 5E adds the final-compositing layer:
- ``PIL_COMPOSITE_REFERENCE``  — legacy: Pillow ``alpha_composite`` over the full
  widget (exact math, unchanged).
- ``PIL_COMPOSITE_OPTIMIZED`` — regional final compositing that is byte-identical
  to the reference but avoids redundant work where provable:
  * fully-transparent widget        -> no-op (canvas unchanged),
  * widget with transparent margins -> composite only the content bbox,
  * widget that fills its bbox and has no fully-transparent source pixels
    (alpha_min > 0) whose destination region is still transparent (no overlap
    with earlier widgets this frame) -> plain ``paste``, which is byte-identical
    to ``alpha_composite`` (src over a transparent destination == src),
  * otherwise                       -> Pillow ``alpha_composite`` unchanged.

No widget renderer is touched: the input RGBA widget is identical in both modes.
"""
from __future__ import annotations

import os

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

# Selection of the final compositing implementation.
#   REFERENCE | OPTIMIZED  (default OPTIMIZED — validated byte-identical to the
#   legacy path by the ETAP 5E 1131-frame full-HUD pixel test; REFERENCE remains
#   available for A/B via the env var).
PIL_COMPOSITE_MODE = os.environ.get("AMD_PIL_COMPOSITE_MODE", "OPTIMIZED").strip().upper()
_COMPOSITE_MODE = PIL_COMPOSITE_MODE


def set_composite_mode(mode: str) -> None:
    """Runtime selection of the final-compositing implementation."""
    global _COMPOSITE_MODE
    _COMPOSITE_MODE = mode.strip().upper()

# Per-widget minimum alpha, cached once (widget alpha structure is static per
# indicator type+size). Used to decide the transparent-destination paste path.
_WIDGET_ALPHA_MIN: dict[tuple, int] = {}


def _alpha_min(overlay: Image.Image, cache_key) -> int:
    """Minimum alpha of *overlay*, cached per widget key+size (alpha is
    rotation-invariant and frame-invariant for the fixed HUD widgets)."""
    if cache_key is not None:
        k = (cache_key, overlay.width, overlay.height)
        if k in _WIDGET_ALPHA_MIN:
            return _WIDGET_ALPHA_MIN[k]
    value = overlay.getchannel("A").getextrema()[0]
    if cache_key is not None:
        _WIDGET_ALPHA_MIN[(cache_key, overlay.width, overlay.height)] = value
    return value


def _intersects_any(box: tuple[int, int, int, int], boxes) -> bool:
    x, y, w, h = box
    for bx, by, bw, bh in boxes:
        if x < bx + bw and bx < x + w and y < by + bh and by < y + h:
            return True
    return False


# ETAP 5I: the plain-paste fast-path is extended to *small* widgets whose
# fully-transparent pixels are clean (RGB == 0).  Over a fully-transparent
# destination Pillow's alpha_composite reduces to ``out == src`` for every
# src_alpha>0 pixel and ``(0,0,0,0)`` for src_alpha==0 — which is exactly what
# a plain paste produces when the alpha==0 pixels are (0,0,0,0).  Byte-identical.
# The check is cheap only for small widgets, so large widgets (charts/gauge,
# which have partial alpha / dirty zeros anyway) keep the exact existing path.
_SMALL_CLEAN_LIMIT_PX = 200 * 200
# Toggle for A/B (REFERENCE = pre-5I, OPTIMIZED = 5I).  Default ON.
_CLEAN_PASTE_ENABLED = os.environ.get("AMD_PIL_CLEAN_PASTE", "1").strip().upper() in {"1", "YES", "ON", "TRUE"}


def set_clean_paste(enabled: bool) -> None:
    """Runtime toggle for the 5I clean-transparency paste fast-path (A/B)."""
    global _CLEAN_PASTE_ENABLED
    _CLEAN_PASTE_ENABLED = bool(enabled)


def _clean_transparency(overlay: Image.Image) -> bool:
    """True when every fully-transparent pixel of *overlay* is (0,0,0,0)."""
    try:
        import numpy as np
        arr = np.asarray(overlay, dtype=np.uint8)
        zero_alpha = arr[..., 3] == 0
        if not zero_alpha.any():
            return True
        return not bool(arr[zero_alpha][..., :3].any())
    except Exception:
        return False


def composite_final(
    base_img: Image.Image,
    overlay: Image.Image,
    x: int,
    y: int,
    prior_bboxes=None,
    cache_key=None,
) -> None:
    """Composite the ready RGBA *overlay* onto *base_img* at (x, y) (top-left).

    Pixel-exact in both modes; only the amount of Pillow work differs.
    """
    if _COMPOSITE_MODE != "OPTIMIZED":
        base_img.alpha_composite(overlay, (x, y))
        return

    bbox = overlay.getbbox()
    if bbox is None:
        # Fully transparent widget — compositing is a no-op on the canvas.
        return

    # ETAP 5I: small clean-transparency widgets over a fully-transparent
    # destination composite byte-identically with a plain paste (see
    # _clean_transparency).  This removes the alpha_composite blend + its
    # internal dest crop for the small HUD text widgets.
    if (
        _CLEAN_PASTE_ENABLED
        and overlay.width * overlay.height <= _SMALL_CLEAN_LIMIT_PX
        and prior_bboxes is not None
        and not _intersects_any((x, y, overlay.width, overlay.height), prior_bboxes)
        and (_alpha_min(overlay, cache_key) > 0 or _clean_transparency(overlay))
    ):
        base_img.paste(overlay, (x, y))
        return

    if bbox != (0, 0, overlay.width, overlay.height):
        # Transparent margins: composite only the content region — but only
        # when the crop temp copy is cheaper than the saved blend area.
        # Measured break-even is around ~70-75% content; below that the crop
        # reduces work, above it the extra temp copy costs more than it saves.
        content_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        full_area = overlay.width * overlay.height
        if content_area >= 0.75 * full_area:
            base_img.alpha_composite(overlay, (x, y))
            return
        content = overlay.crop(bbox)
        base_img.alpha_composite(content, (x + bbox[0], y + bbox[1]))
        return

    # Content fills the whole widget.  The plain-paste shortcut is only
    # byte-identical when the source has no fully-transparent (non-zero RGB)
    # pixels and the destination region is still fully transparent.
    if _alpha_min(overlay, cache_key) <= 0:
        base_img.alpha_composite(overlay, (x, y))
        return
    if prior_bboxes is not None and _intersects_any(
        (x, y, overlay.width, overlay.height), prior_bboxes
    ):
        base_img.alpha_composite(overlay, (x, y))
        return
    base_img.paste(overlay, (x, y))


def rotated_paste(
    base_img: Image.Image,
    overlay: Image.Image,
    center_x: int,
    center_y: int,
    rotation: int,
    prior_bboxes=None,
    cache_key=None,
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
    composite_final(base_img, overlay, x, y, prior_bboxes, cache_key)
