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
    
    cache_key = _static_cache_key(
        "time_block", canvas_w, canvas_h, font_path,
        date_text, time_text, cfg.get("label", "Czas"),
        cfg.get("font_label"), cfg.get("font_date"), cfg.get("font_time")
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

    # Ensure sufficient temporary canvas size without hardcoded undersized clipping
    label_txt = cfg.get("label", "Czas")
    b_label = font_label.getbbox(label_txt) if hasattr(font_label, "getbbox") else (0, 0, 100, label_px)
    b_date = font_date.getbbox(date_text) if hasattr(font_date, "getbbox") else (0, 0, 200, date_px)
    b_time = font_time.getbbox(time_text) if hasattr(font_time, "getbbox") else (0, 0, 200, time_px)

    req_w = max(b_label[2] - b_label[0], b_date[2] - b_date[0], b_time[2] - b_time[0]) + outline * 4 + 50
    req_h = int(label_px * 1.3) + int(date_px * 1.2) + (b_time[3] - b_time[1]) + outline * 4 + 50

    tmp = Image.new(
        "RGBA",
        (max(req_w, s(25.0, canvas_w)), max(req_h, s(15.0, canvas_h))),
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
