"""Text-form indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import s, parse_hex_color
from src.indicators.icons import render_icon


def _render_text_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    """Render a text-form indicator."""
    v_str = formatted_val if formatted_val is not None else f"{value:.1f} {unit}"
    
    if label and v_str:
        txt = f"{label}: {v_str}"
    elif label:
        txt = label
    else:
        txt = v_str
        
    if not txt:
        return None, 0, 0, None
        
    text_color = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)

    from src.indicators.helpers import _STATIC_CACHE, _static_cache_key

    cache_key = _static_cache_key(
        "text_indicator", canvas_w, canvas_h, font_path, key, txt, text_color, outline, fs,
        cfg.get("icon", "none")
    )
    px_x = s(cfg["x"], canvas_w)
    px_y = s(cfg["y"], canvas_h)
    cached = _STATIC_CACHE.get(cache_key)
    if cached is not None:
        return cached, px_x, px_y, None
    
    icon = render_icon(cfg.get("icon"), max(8, int(fs * 0.95)))
    gap = max(2, int(fs * 0.18)) if icon else 0
    txt_w = int(font.getlength(txt) + outline * 4 + (icon.width + gap if icon else 0))
    tmp = Image.new("RGBA", (txt_w, int(fs * 2)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    text_x = outline + (icon.width + gap if icon else 0)
    if icon:
        tmp.alpha_composite(icon, (outline, max(0, (tmp.height - icon.height) // 2)))
    draw.text(
        (text_x, 0), txt, font=font,
        fill=(text_color[0], text_color[1], text_color[2], 255),
        stroke_width=outline, stroke_fill=(0, 0, 0, 255),
    )
    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0, None

    cropped = tmp.crop(bbox)
    _STATIC_CACHE[cache_key] = cropped
    return cropped, px_x, px_y, None
