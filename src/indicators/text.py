from __future__ import annotations
from typing import Any

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import (
    _BoundedStaticCache,
    _static_cache_key,
    draw_text_with_graphic_degree,
    load_font,
    measure_text_with_graphic_degree,
    parse_hex_color,
    s,
)
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


def _position_unit(tmp, txt, suffix, font, xy, fill, outline, icon, icon_xy, dx, dy, rotation):
    """Move only the unit; keep the old numeric ink anchored after tight crop."""
    prefix = txt[:-len(suffix)]
    value_layer = Image.new("RGBA", tmp.size)
    if icon:
        value_layer.alpha_composite(icon, icon_xy)
    draw = ImageDraw.Draw(value_layer)
    style = dict(font=font, fill=fill, stroke_width=outline,
                 stroke_fill=(0, 0, 0, 255), anchor="la")
    draw_text_with_graphic_degree(draw, xy, prefix, **style)
    unit_layer = Image.new("RGBA", tmp.size)
    advance = (measure_text_with_graphic_degree(draw, prefix, font)[0]
               if "°" in prefix else draw.textlength(prefix, font=font))
    draw_text_with_graphic_degree(
        ImageDraw.Draw(unit_layer), (xy[0] + advance, xy[1]), suffix, **style,
    )
    value_box, unit_box = value_layer.getbbox(), unit_layer.getbbox()
    if not unit_box:
        return (value_layer.crop(value_box) if value_box else tmp), (0, 0)
    original_boxes = [b for b in (value_box, unit_box) if b]
    old_box = (min(b[0] for b in original_boxes), min(b[1] for b in original_boxes),
               max(b[2] for b in original_boxes), max(b[3] for b in original_boxes))
    boxes = [value_box] if value_box else []
    boxes.append((unit_box[0] + dx, unit_box[1] + dy, unit_box[2] + dx, unit_box[3] + dy))
    box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
           max(b[2] for b in boxes), max(b[3] for b in boxes))
    result = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]))
    if value_box:
        result.alpha_composite(value_layer.crop(value_box), (value_box[0] - box[0], value_box[1] - box[1]))
    result.alpha_composite(unit_layer.crop(unit_box), (unit_box[0] + dx - box[0], unit_box[1] + dy - box[1]))
    ox, oy = box[0] - old_box[0], box[1] - old_box[1]
    dw = old_box[2] - old_box[0] - result.width
    dh = old_box[3] - old_box[1] - result.height
    shift = {0: (ox, oy), 90: (oy, dw - ox),
             180: (dw - ox, dh - oy), 270: (dh - oy, ox)}.get(rotation, (ox, oy))
    return result, shift


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
    suffix = str(unit or "") if cfg.get("show_units", True) else ""
    if cfg.get("show_units", True) and txt.endswith("°C"):
        suffix = "°C"  # Move the graphic degree ring with the temperature unit.
    if not suffix or not txt.endswith(suffix):
        suffix = ""
    # Distance is in logical pixels at 1080p; Unit X/Y use the same canvas
    # fractions as the existing Text X/Y controls. Zero preserves legacy ink.
    unit_dx = int(round(float(cfg.get("text_distance", 0.0)) * min_dim / 1080.0
                        + float(cfg.get("unit_offset_x", 0.0)) * canvas_w)) if suffix else 0
    unit_dy = int(round(float(cfg.get("unit_offset_y", 0.0)) * canvas_h)) if suffix else 0
    rotation = int(cfg.get("rotation", 0)) % 360

    cache_key = _static_cache_key(
        "text_ind_v4", canvas_w, canvas_h, font_path, key, txt, text_color, outline_int, fs_int,
        icon_name, suffix, unit_dx, unit_dy, rotation
    )
    ox = int(round(float(cfg.get("text_offset_x", 0.0)) * canvas_w))
    oy = int(round(float(cfg.get("text_offset_y", 0.0)) * canvas_h))
    px_x = s(cfg["x"], canvas_w) + ox
    px_y = s(cfg["y"], canvas_h) + oy
    
    cached = _TEXT_INDICATOR_CACHE.get(cache_key)
    if cached is not None:
        dx, dy = cached.info.get("text_unit_origin", (0, 0))
        return cached, px_x + dx, px_y + dy, None

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
    if "°" in txt:
        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        raw_w = measure_text_with_graphic_degree(probe_draw, txt, font, stroke_width=outline_int)[0]
    else:
        raw_w = font.getlength(txt)
    txt_w = int(raw_w + outline_int * 6 + (icon.width + gap if icon else 0) + 10)

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

    if suffix and (unit_dx or unit_dy):
        cropped, shift = _position_unit(
            tmp, txt, suffix, font, (text_x, text_y), (*text_color[:3], 255), outline_int,
            icon, (icon_x, icon_y) if icon else (0, 0), unit_dx, unit_dy, rotation,
        )
        cropped.info["text_unit_origin"] = shift
        _TEXT_INDICATOR_CACHE[cache_key] = cropped
        return cropped, px_x + shift[0], px_y + shift[1], None
    draw_text_with_graphic_degree(
        draw,
        (text_x, text_y), txt, font=font,
        fill=(text_color[0], text_color[1], text_color[2], 255),
        stroke_width=outline_int, stroke_fill=(0, 0, 0, 255),
        anchor="la",
    )
    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0, None

    cropped = tmp.crop(bbox)
    _TEXT_INDICATOR_CACHE[cache_key] = cropped
    return cropped, px_x, px_y, None
