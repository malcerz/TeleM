"""Shared helper utilities for indicator rendering.

These are extracted from ``overlay_renderer.py`` so that per-form
indicator modules can import them without circular dependencies.
"""

from __future__ import annotations

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
    """Scale a relative value (0.0-1.0 range) to an absolute pixel size."""
    return max(1, int(round(value * base)))


# ── Font loading ───────────────────────────────────────────────────────────

def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font from cache or disk. Falls back to default PIL font on failure."""
    key = (str(font_path), int(size))
    font = FONT_CACHE.get(key)
    if font is not None:
        return font
    try:
        font = ImageFont.truetype(str(font_path), size=int(size))
    except Exception:
        font = ImageFont.load_default()
    FONT_CACHE[key] = font
    return font


# ── Static background cache ────────────────────────────────────────────────

_STATIC_CACHE: dict[tuple, Image.Image] = {}
"""Cache for indicator backgrounds that don't change between frames
(gauge tick marks, chart axes, bar tracks, etc.).
The key is a tuple of all parameters that affect the static image."""


def _static_cache_key(*args) -> tuple:
    """Build a hashable cache key from a set of static parameters."""
    return args
