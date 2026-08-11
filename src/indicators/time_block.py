"""Time block indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import load_font, s


def render_time_block(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    date_text: str,
    time_text: str,
) -> tuple[Optional[Image.Image], int, int]:
    """Render the date/time block indicator.

    Returns:
        (overlay_img, px_x, px_y) or (None, 0, 0) if disabled or missing.
    """
    cfg = layout.get("indicators", {}).get("time_block")
    if cfg is None or not cfg.get("enabled", True):
        return None, 0, 0

    from src.indicators.helpers import _STATIC_CACHE, _static_cache_key
    
    tb_cfg_str = str(sorted(cfg.items()))
    global_cfg_str = str(sorted(layout.get("global", {}).items()))
    
    cache_key = _static_cache_key(
        "time_block", canvas_w, canvas_h, font_path,
        date_text, time_text, tb_cfg_str, global_cfg_str
    )
    px_x = s(cfg["x"], canvas_w)
    px_y = s(cfg["y"], canvas_h)
    cached = _STATIC_CACHE.get(cache_key)
    if cached is not None:
        return cached, px_x, px_y

    min_dim = min(canvas_w, canvas_h)
    outline_raw = int(layout["global"].get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))

    label_px = max(12, s(cfg["font_label"], min_dim))
    date_px = max(14, s(cfg["font_date"], min_dim))
    time_px = max(14, s(cfg["font_time"], min_dim))

    font_label = load_font(font_path, label_px)
    font_date = load_font(font_path, date_px)
    font_time = load_font(font_path, time_px)

    tmp = Image.new(
        "RGBA",
        (max(200, s(0.25, canvas_w)), max(100, s(0.12, canvas_h))),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(tmp)

    y = 0
    draw.text(
        (0, y),
        cfg.get("label", "Czas"),
        font=font_label,
        fill=(210, 210, 210, 255),
        stroke_width=outline,
        stroke_fill=(0, 0, 0, 255),
    )
    y += int(label_px * 1.3)

    draw.text(
        (0, y),
        date_text,
        font=font_date,
        fill=(255, 255, 255, 255),
        stroke_width=outline,
        stroke_fill=(0, 0, 0, 255),
    )
    y += int(date_px * 1.2)

    draw.text(
        (0, y),
        time_text,
        font=font_time,
        fill=(255, 255, 255, 255),
        stroke_width=outline,
        stroke_fill=(0, 0, 0, 255),
    )

    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0

    cropped = tmp.crop(bbox)
    _STATIC_CACHE[cache_key] = cropped
    return cropped, px_x, px_y
