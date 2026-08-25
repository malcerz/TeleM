"""Shared helper utilities for indicator rendering.

These are extracted from ``overlay_renderer.py`` so that per-form
indicator modules can import them without circular dependencies.
"""

from __future__ import annotations

import time
from typing import Any, Optional

try:
    from PIL import Image, ImageFont
except ImportError:
    Image = None  # type: ignore
    ImageFont = None  # type: ignore


# ── Font cache ──────────────────────────────────────────────────────────────

FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def load_font_cache_small(size: int) -> Optional[ImageFont.ImageFont]:
    """Return the default PIL font at the given size (cached). Used for chart axis labels."""
    key = ("__builtin_default__", int(size))
    if key in FONT_CACHE:
        return FONT_CACHE[key]  # type: ignore[return-value]
    try:
        font = ImageFont.load_default()
        FONT_CACHE[key] = font
        return font
    except Exception:
        return None


# ── Colour parsing ─────────────────────────────────────────────────────────

def parse_hex_color(hex_str: Any) -> Optional[tuple[int, int, int]]:
    """Convert a hex colour string (e.g. '#FF3232' or 'FF3232') to an RGB tuple.
    Returns None on failure."""
    if not hex_str or not isinstance(hex_str, str):
        return None
    s = hex_str.strip().lstrip("#")
    try:
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        elif len(s) == 3:
            return (int(s[0], 16) * 17, int(s[1], 16) * 17, int(s[2], 16) * 17)
    except Exception:
        pass
    return None


def _parse_marker_color(hex_color: str) -> tuple[int, int, int, int]:
    """Convert '#RRGGBB' or '#RRGGBBAA' hex to RGBA tuple.
    Falls back to white on failure."""
    if not hex_color or not isinstance(hex_color, str):
        return (255, 255, 255, 255)
    s = hex_color.strip().lstrip("#")
    try:
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)
        elif len(s) == 8:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
    except Exception:
        pass
    return (255, 255, 255, 255)


# ── Scaling ────────────────────────────────────────────────────────────────

def s(value: float, base: int) -> int:
    """Scale a relative percentage value (0.0-100.0 range, where 50 is center/50%) to an absolute pixel size."""
    return max(1, int(round((value / 100.0) * base)))



# ── Font loading ───────────────────────────────────────────────────────────

def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font from cache or disk. Falls back to default PIL font on failure."""
    from src.indicators.profiling import get_overlay_profiler
    profiler = get_overlay_profiler()
    lookup_started = time.perf_counter()
    key = (str(font_path), int(size))
    font = FONT_CACHE.get(key)
    if font is not None:
        profiler.record_operation(
            "font cache lookup", (time.perf_counter() - lookup_started) * 1000.0
        )
        return font
    try:
        font = ImageFont.truetype(str(font_path), size=int(size))
    except Exception:
        font = ImageFont.load_default()
    FONT_CACHE[key] = font
    profiler.record_operation(
        "font cache lookup", (time.perf_counter() - lookup_started) * 1000.0
    )
    return font


# ── Static background cache ────────────────────────────────────────────────

_STATIC_CACHE: dict[tuple, Image.Image] = {}
"""Cache for indicator backgrounds that don't change between frames
(gauge tick marks, chart axes, bar tracks, etc.).
The key is a tuple of all parameters that affect the static image."""


def _static_cache_key(*args) -> tuple:
    """Build a hashable cache key from a set of static parameters."""
    return args


# ── ETAP 5Q compose optimization toggle ────────────────────────────────────
_COMPOSE_5Q: Optional[bool] = None


def compose_5q_optimized() -> bool:
    """ETAP 5Q: are the CPU compose optimizations enabled?

    Reads ``AMD_COMPOSE_5Q`` once per process (REFERENCE = current code,
    OPTIMIZED = value-keyed text-tile caches).  Default OPTIMIZED since ETAP
    5W: it is byte-exact (pixel-exact gate), its caches are bounded per source
    (verified constant across a 20-export soak), and at the pool8 production
    config it is faster (REF ~34.9 FPS vs OPT ~37.5 FPS).  AMD_COMPOSE_5Q
    override (REFERENCE) remains honored.
    """
    global _COMPOSE_5Q
    if _COMPOSE_5Q is None:
        import os
        _COMPOSE_5Q = os.environ.get(
            "AMD_COMPOSE_5Q", "OPTIMIZED"
        ).strip().upper() == "OPTIMIZED"
    return _COMPOSE_5Q


_MAP_MASK_CACHE: dict[tuple[int, int], Image.Image] = {}


def apply_map_shape(img, shape: str):
    """Apply the configured map shape to a rendered map image.

    - ``"round"`` (or ``"circle"``) → circular crop (alpha mask).
    - anything else → square (the map is already rendered square).

    Returns the (possibly modified) image.
    """
    if img is None:
        return img
    if str(shape).lower() not in ("round", "circle"):
        return img
    try:
        from PIL import ImageDraw

        w, h = img.size
        mask_key = (w, h)
        mask = _MAP_MASK_CACHE.get(mask_key)
        if mask is None:
            mask = Image.new("L", (w, h), 0)
            d = ImageDraw.Draw(mask)
            d.ellipse((0, 0, w - 1, h - 1), fill=255)
            _MAP_MASK_CACHE[mask_key] = mask
        img = img.copy()
        img.putalpha(mask)
    except Exception:
        pass
    return img
