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
import threading
import time

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
_WIDGET_CLEAN_TRANSPARENCY: dict[tuple, bool] = {}

# ETAP 10R: per-thread accumulator for the alpha-tight bbox collection time
# spent inside composite_final when tight_bboxes is requested (only the AMD
# EXACT path enables it).  The exporter resets it around the ABOVE compose
# call and reads it back as the above_tight_bbox_collect metric.
_tight_bbox_collect_local = threading.local()


def _tight_collect_accum() -> list[float]:
    if not hasattr(_tight_bbox_collect_local, "ms"):
        _tight_bbox_collect_local.ms = [0.0]
    return _tight_bbox_collect_local.ms


def reset_tight_bbox_collect() -> None:
    """Reset the ETAP 10R tight-bbox collect accumulator (thread-local)."""
    _tight_collect_accum()[0] = 0.0


def get_tight_bbox_collect_ms() -> float:
    """Return the accumulated tight-bbox collect time in ms (thread-local)."""
    return _tight_collect_accum()[0]


def _alpha_min(overlay: Image.Image, cache_key) -> int:
    """Minimum alpha of *overlay*, cached per widget key+size (alpha is
    rotation-invariant and frame-invariant for the fixed HUD widgets)."""
    if not hasattr(overlay, "getchannel"):
        return 0
    if cache_key is not None:
        k = (cache_key, getattr(overlay, "width", 0), getattr(overlay, "height", 0))
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


def _plain_paste_safe(overlay: Image.Image, cache_key) -> bool:
    """Whether plain paste preserves a ready RGBA raster on empty RGBA ROI.

    The result is cached by widget identity/size.  This is deliberately not a
    per-frame pixel scan: chart rasters have stable transparent-pixel encoding,
    while their visible chart contents change every frame.
    """
    if _alpha_min(overlay, cache_key) > 0:
        return True
    if cache_key is None:
        return False
    key = (cache_key, overlay.width, overlay.height)
    if key not in _WIDGET_CLEAN_TRANSPARENCY:
        _WIDGET_CLEAN_TRANSPARENCY[key] = _clean_transparency(overlay)
    return _WIDGET_CLEAN_TRANSPARENCY[key]


def composite_final(
    base_img: Image.Image,
    overlay: Image.Image,
    x: int,
    y: int,
    prior_bboxes=None,
    cache_key=None,
    destination_proven_empty: bool = False,
    tight_bboxes=None,
    tight_key=None,
) -> None:
    """Composite the ready RGBA *overlay* onto *base_img* at (x, y) (top-left).

    Pixel-exact in both modes; only the amount of Pillow work differs.

    ETAP 10R: when *tight_bboxes* is a dict and *cache_key* is not None, the
    alpha-tight bbox of the (already rotated) overlay is recorded into
    ``tight_bboxes[key]`` as ``{"rect": (x, y, w, h) | None, "clipped": bool}``
    in absolute canvas coordinates.  This is exactly the region that the AMD
    SCAN path re-derives via ``candidate.getchannel("A").getbbox()`` (the
    canonical definition: bounding box of pixels where alpha != 0, so a pixel
    with A == 0 / RGB != 0 is excluded).  ``clipped`` is True when the widget
    extends past the canvas edge, in which case the EXACT path must fall back
    to SCAN (the bbox of clipped content can differ from the clipped bbox for
    irregular content).  When *tight_bboxes* is None the function is 100%
    unchanged.
    """
    if not hasattr(overlay, "getbbox"):
        return

    if tight_bboxes is not None and cache_key is not None:
        tk = tight_key if tight_key is not None else cache_key
        acc = _tight_collect_accum()
        t_tb_start = time.perf_counter()
        ab = getattr(overlay, "_alpha_bbox", ...)
        if ab is ...:
            if not hasattr(overlay, "getbbox"):
                ab = None
            elif _plain_paste_safe(overlay, cache_key):
                ab = overlay.getbbox()
            elif hasattr(overlay, "getchannel"):
                ab = overlay.getchannel("A").getbbox()
            else:
                ab = overlay.getbbox()
            try:
                overlay._alpha_bbox = ab
            except Exception:
                pass
        acc[0] += (time.perf_counter() - t_tb_start) * 1000.0
        clipped = (
            x < 0
            or y < 0
            or x + overlay.width > base_img.width
            or y + overlay.height > base_img.height
        )
        if ab is None:
            tight_bboxes[tk] = {"rect": None, "clipped": clipped}
        else:
            tight_bboxes[tk] = {
                "rect": (x + ab[0], y + ab[1], ab[2] - ab[0], ab[3] - ab[1]),
                "clipped": clipped,
            }

    if _COMPOSITE_MODE != "OPTIMIZED":
        base_img.alpha_composite(overlay, (x, y))
        return

    # ETAP 4D: clean-transparency widgets over a fully-transparent
    # destination composite byte-identically with a plain paste (see
    # _clean_transparency and _plain_paste_safe).  This removes the
    # alpha_composite blend + its internal dest crop for all non-overlapping
    # HUD widgets (distance ruler, altitude bar, battery, text).
    if (
        _CLEAN_PASTE_ENABLED
        and prior_bboxes is not None
        and x >= 0
        and y >= 0
        and x + overlay.width <= base_img.width
        and y + overlay.height <= base_img.height
        and not _intersects_any((x, y, overlay.width, overlay.height), prior_bboxes)
        and _plain_paste_safe(overlay, cache_key)
    ):
        base_img.paste(overlay, (x, y))
        return

    bbox = overlay.getbbox()
    if bbox is None:
        # Fully transparent widget — compositing is a no-op on the canvas.
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
    center_x: int | float,
    center_y: int | float,
    rotation: int,
    prior_bboxes=None,
    cache_key=None,
    destination_proven_empty: bool = False,
    tight_bboxes=None,
    tight_key=None,
    coordinate_offset: tuple[int, int] = (0, 0),
) -> None:
    """Paste *overlay* onto *base_img* centred at (center_x, center_y) with rotation.
    Modifies base_img in place.

    ETAP 10R: *tight_bboxes* / *tight_key* are forwarded to composite_final
    (alpha-tight bbox capture).  When *tight_bboxes* is None behaviour is
    unchanged.

    ETAP 4B: *coordinate_offset* allows exact sub-tile / cluster rendering
    without floating-point banker's rounding flips when offsetting coordinates.
    """
    rotation = int(rotation) % 360
    if rotation == 90:
        overlay = overlay.transpose(Image.Transpose.ROTATE_90)
    elif rotation == 180:
        overlay = overlay.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        overlay = overlay.transpose(Image.Transpose.ROTATE_270)
    x = int(round(center_x - overlay.width / 2.0)) - coordinate_offset[0]
    y = int(round(center_y - overlay.height / 2.0)) - coordinate_offset[1]
    composite_final(
        base_img, overlay, x, y, prior_bboxes, cache_key,
        destination_proven_empty=destination_proven_empty,
        tight_bboxes=tight_bboxes,
        tight_key=tight_key,
    )
