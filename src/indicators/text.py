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
        "text_ind_v3", canvas_w, canvas_h, font_path, key, txt, text_color, outline_int, fs_int,
        icon_name
    )
    px_x = s(cfg["x"], canvas_w)
    px_y = s(cfg["y"], canvas_h)
    
    cached = _TEXT_INDICATOR_CACHE.get(cache_key)
    if cached is not None:
        return cached, px_x, px_y, None

    if font is None:
        font = load_font(font_path, fs_int)

    icon = render_icon(icon_name, max(8, int(round(fs_int * 0.90))))
    gap = max(3, int(round(fs_int * 0.22))) if icon else 0

    # Calculate optical text metrics (aligned with font capital/digit baseline & optical center)
    ref_bbox = font.getbbox("HX0123456789") if hasattr(font, "getbbox") else (0, 0, 0, fs_int)
    text_optical_mid = (ref_bbox[1] + ref_bbox[3]) / 2.0
    text_h = max(fs_int, ref_bbox[3] - ref_bbox[1])

    pad = outline_int + 4
    canvas_h = max(int(text_h + pad * 2), int((icon.height if icon else 0) + pad * 2), int(fs_int * 2))
    txt_w = int(font.getlength(txt) + outline_int * 6 + (icon.width + gap if icon else 0) + 10)

    tmp = Image.new("RGBA", (txt_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)

    text_y = pad
    actual_text_mid = text_y + text_optical_mid

    if icon:
        icon_x = outline_int
        icon_y = max(outline_int, int(round(actual_text_mid - icon.height / 2.0)))
        tmp.alpha_composite(icon, (icon_x, icon_y))
        text_x = icon_x + icon.width + gap
    else:
        text_x = outline_int

    draw.text(
        (text_x, text_y), txt, font=font,
        fill=(text_color[0], text_color[1], text_color[2], 255),
        stroke_width=outline_int, stroke_fill=(0, 0, 0, 255),
    )
    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0, None

    cropped = tmp.crop(bbox)
    _TEXT_INDICATOR_CACHE[cache_key] = cropped
    return cropped, px_x, px_y, None
