"""Custom text indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import load_font, parse_hex_color, _STATIC_CACHE, _static_cache_key


def render_custom_text(
    canvas_w: int, canvas_h: int, font_path: str, cfg: dict[str, Any],
    stroke_width: int = 2,
) -> tuple[Optional[Image.Image], int, int]:
    """Render a single custom text overlay.

    Args:
        canvas_w: Canvas width in pixels.
        canvas_h: Canvas height in pixels.
        font_path: Path to the TrueType font file.
        cfg: Dict with keys: enabled, text, x, y, rotation, font_size, color.
        stroke_width: Outline thickness in pixels (default 2).

    Returns:
        (overlay_img, px_x, px_y) or (None, 0, 0) if disabled.
    """
    if not cfg.get("enabled", True):
        return None, 0, 0
    text = str(cfg.get("text", ""))
    if not text:
        return None, 0, 0
    min_dim = min(canvas_w, canvas_h)
    font_size_px = max(8, int(round((cfg.get("font_size", 2.5) / 100.0) * min_dim)))
    color_hex = cfg.get("color", "#FFFFFF")
    px = int(round((cfg.get("x", 50.0) / 100.0) * canvas_w))
    py = int(round((cfg.get("y", 50.0) / 100.0) * canvas_h))

    cache_key = _static_cache_key("custom_text", canvas_w, canvas_h, font_path, text, font_size_px, color_hex, stroke_width)
    cached = _STATIC_CACHE.get(cache_key)
    if cached is not None:
        return cached, px, py

    font = load_font(font_path, font_size_px)
    rgb = parse_hex_color(color_hex)
    if rgb is None:
        rgb = (255, 255, 255)
    fill_color = (rgb[0], rgb[1], rgb[2], 255)
    # Measure text via a tiny temp image (avoids (canvas_w × font_size) allocation)
    _tmp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    _draw = ImageDraw.Draw(_tmp)
    bbox = _draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    overlay = Image.new("RGBA", (tw + 8, th + 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.text((4, 4), text, font=font, fill=fill_color, stroke_width=stroke_width, stroke_fill=(0, 0, 0, 200))
    _STATIC_CACHE[cache_key] = overlay
    return overlay, px, py
