from __future__ import annotations
from typing import Any

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import s, parse_hex_color, load_font, _BoundedStaticCache, _static_cache_key
from src.indicators.icons import render_icon

# Dedicated bounded cache for text indicator rasters (ETAP 3C)
_TEXT_INDICATOR_CACHE = _BoundedStaticCache(max_entries=512)


def get_text_cache_stats() -> dict[str, Any]:
    """Return text indicator cache performance diagnostics."""
    hits = _TEXT_INDICATOR_CACHE.hits
    misses = _TEXT_INDICATOR_CACHE.misses
    total = hits + misses
    hit_rate = (hits / total * 100.0) if total > 0 else 0.0
    return {
        "entries": len(_TEXT_INDICATOR_CACHE),
        "max_entries": _TEXT_INDICATOR_CACHE.max_entries,
        "hits": hits,
        "misses": misses,
        "hit_rate_pct": hit_rate,
    }


def clear_text_cache() -> None:
    """Clear text indicator cache."""
    _TEXT_INDICATOR_CACHE.clear()
    _TEXT_INDICATOR_CACHE.hits = 0
    _TEXT_INDICATOR_CACHE.misses = 0


def _render_text_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    v_str = formatted_val if formatted_val is not None else (f"{value:.1f} {unit}".strip() if value is not None else f"-- {unit}".strip())
    
    if label and v_str:
        txt = f"{label}: {v_str}"
    elif label:
        txt = label
    else:
        txt = v_str
        
    if not txt:
        return None, 0, 0, None
        
    text_color = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
    icon_name = cfg.get("icon", "none")
    fs_int = max(8, int(fs))
    outline_int = int(outline)

    cache_key = _static_cache_key(
        "text_ind_v2", canvas_w, canvas_h, font_path, key, txt, text_color, outline_int, fs_int,
        icon_name
    )
    px_x = s(cfg["x"], canvas_w)
    px_y = s(cfg["y"], canvas_h)
    
    cached = _TEXT_INDICATOR_CACHE.get(cache_key)
    if cached is not None:
        return cached, px_x, px_y, None

    if font is None:
        font = load_font(font_path, fs_int)

    icon = render_icon(icon_name, max(8, int(fs_int * 0.95)))
    gap = max(2, int(fs_int * 0.18)) if icon else 0
    txt_w = int(font.getlength(txt) + outline_int * 4 + (icon.width + gap if icon else 0))
    tmp = Image.new("RGBA", (txt_w, int(fs_int * 2)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    text_x = outline_int + (icon.width + gap if icon else 0)
    if icon:
        tmp.alpha_composite(icon, (outline_int, max(0, (tmp.height - icon.height) // 2)))
    draw.text(
        (text_x, 0), txt, font=font,
        fill=(text_color[0], text_color[1], text_color[2], 255),
        stroke_width=outline_int, stroke_fill=(0, 0, 0, 255),
    )
    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0, None

    cropped = tmp.crop(bbox)
    _TEXT_INDICATOR_CACHE[cache_key] = cropped
    return cropped, px_x, px_y, None
