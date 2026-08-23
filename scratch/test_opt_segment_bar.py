import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import Any, Optional
from math import ceil
from PIL import Image, ImageDraw

from src.indicators.helpers import (
    load_font, parse_hex_color, s, _BoundedStaticCache, _static_cache_key
)
from src.indicators.icons import render_icon
from src.indicators.bar import (
    _rgb, _rgba, _clamp01, _fraction, _fmt_number,
    _gradient_colour, _text_size, _draw_text_bounded
)

# Bounded LRU caches for segment bar sub-components
_SEG_BASE_CACHE = _BoundedStaticCache(max_entries=32)
_SEG_ACTIVE_CACHE = _BoundedStaticCache(max_entries=64)
_SEG_ICON_CACHE = _BoundedStaticCache(max_entries=16)


def _get_seg_icon(icon_name: str, icon_size: int) -> Optional[Image.Image]:
    if not icon_name or icon_name == "none":
        return None
    key = (icon_name, icon_size)
    ic = _SEG_ICON_CACHE.get(key)
    if ic is not None:
        return ic
    ic = render_icon(icon_name, icon_size)
    if ic is not None:
        _SEG_ICON_CACHE[key] = ic
    return ic


def _build_seg_base_layer(
    raster_w: int,
    raster_h: int,
    ss: int,
    pad_x: int,
    top_pad: int,
    value_h: int,
    value_gap: int,
    seg_area_h: int,
    seg_top: int,
    seg_bottom: int,
    bottom_y: int,
    bottom_text_h: int,
    segments: int,
    gap: int,
    radius: int,
    seg_w: float,
    grow_height: bool,
    grow_start: float,
    inactive: tuple[int, int, int, int],
    show_min: bool,
    show_max: bool,
    show_label: bool,
    val_min: float,
    val_max: float,
    decimals: int,
    range_units: bool,
    unit: str,
    label: str,
    font_path: str,
    range_fs: int,
    label_fs: int,
    text_stroke: int,
    dim_color: tuple[int, int, int, int],
    text_color: tuple[int, int, int, int],
    icon_name: str | None,
    uppercase_label: bool,
) -> Image.Image:
    base_img = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(base_img)

    # 1. Inactive segments with shadow
    for i in range(segments):
        p = i / max(1, segments - 1)
        h_mult = grow_start + (1.0 - grow_start) * p if grow_height else 1.0
        sh = max(2 * ss, int(round(seg_area_h * h_mult)))
        x1 = int(round(pad_x + i * (seg_w + gap)))
        x2 = int(round(pad_x + i * (seg_w + gap) + seg_w - 1))
        y2 = seg_bottom
        y1 = y2 - sh
        shadow_off = max(1, ss)
        d.rounded_rectangle(
            (x1 + shadow_off, y1 + shadow_off, x2 + shadow_off, y2 + shadow_off),
            radius=radius, fill=(0, 0, 0, 75),
        )
        d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=inactive)

    range_font = load_font(font_path, range_fs)
    label_font = load_font(font_path, label_fs)

    # 2. Range min/max labels
    if show_min:
        min_txt = _fmt_number(val_min, decimals)
        if range_units and unit:
            min_txt = f"{min_txt} {unit}"
        _draw_text_bounded(
            d, (pad_x, bottom_y), min_txt,
            font=range_font, fill=dim_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor="la",
        )

    if show_max:
        max_txt = _fmt_number(val_max, decimals)
        if range_units and unit:
            max_txt = f"{max_txt} {unit}"
        _draw_text_bounded(
            d, (raster_w - pad_x, bottom_y), max_txt,
            font=range_font, fill=dim_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor="ra",
        )

    # 3. Label and icon
    if show_label and label:
        icon = _get_seg_icon(icon_name, max(10 * ss, int(label_fs * 1.1)))
        if icon:
            ix = max(0, int((raster_w - icon.width - int(label_font.getlength(str(label)))) / 2) - 3 * ss)
            iy = max(0, int(bottom_y + (bottom_text_h - icon.height) / 2))
            base_img.alpha_composite(icon, (ix, iy))
        _draw_text_bounded(
            d, (raster_w / 2, bottom_y), str(label).upper() if uppercase_label else str(label),
            font=label_font, fill=text_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor="ma",
        )

    return base_img


def _get_seg_active_layer(
    active: int,
    segments: int,
    raster_w: int,
    raster_h: int,
    ss: int,
    pad_x: int,
    seg_bottom: int,
    seg_area_h: int,
    gap: int,
    radius: int,
    seg_w: float,
    grow_height: bool,
    grow_start: float,
    gradient_tuple: tuple[str, ...],
) -> Image.Image | None:
    if active <= 0:
        return None

    key = (
        "seg_act", active, segments, raster_w, raster_h, ss, pad_x, seg_bottom,
        seg_area_h, gap, radius, round(seg_w, 2), grow_height, round(grow_start, 2), gradient_tuple
    )
    layer = _SEG_ACTIVE_CACHE.get(key)
    if layer is not None:
        return layer

    layer = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    for i in range(active):
        p = i / max(1, segments - 1)
        h_mult = grow_start + (1.0 - grow_start) * p if grow_height else 1.0
        sh = max(2 * ss, int(round(seg_area_h * h_mult)))
        x1 = int(round(pad_x + i * (seg_w + gap)))
        x2 = int(round(pad_x + i * (seg_w + gap) + seg_w - 1))
        y2 = seg_bottom
        y1 = y2 - sh
        colour = _gradient_colour(gradient_tuple, p)
        fill = (*colour, 255)
        d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill)

    _SEG_ACTIVE_CACHE[key] = layer
    return layer


def optimized_render_segments(
    *,
    canvas_w: int,
    canvas_h: int,
    font_path: str,
    value: float | None,
    unit: str,
    label: str,
    cfg: dict[str, Any],
    val_min: float,
    val_max: float,
    size_px: int,
    fs: int,
    outline: int,
    ss: int,
    formatted_val: str | None,
):
    from src.indicators.helpers import _STATIC_CACHE, _static_cache_key

    cache_key = _static_cache_key(
        "seg_bar", canvas_w, canvas_h, font_path,
        value, formatted_val, unit, label,
        size_px, fs, outline, ss,
        cfg.get("segments", 20), cfg.get("icon", "none")
    )
    cached = _STATIC_CACHE.get(cache_key)
    if cached is not None:
        return cached

    ss = max(1, int(ss))
    width = max(80 * ss, int(size_px * ss))
    segments = max(2, int(cfg.get("segments", 20)))
    gap = max(0, int(round(float(cfg.get("segment_gap", 3)) * ss)))
    radius = max(0, int(round(float(cfg.get("segment_radius", 1)) * ss)))
    decimals = max(0, int(cfg.get("decimals", 1)))

    value_fs = max(10 * ss, int(round(float(cfg.get("value_font_scale", 1.70)) * fs * ss)))
    label_fs = max(7 * ss, int(round(float(cfg.get("label_font_scale", 0.72)) * fs * ss)))
    range_fs = max(7 * ss, int(round(float(cfg.get("range_font_scale", 0.82)) * fs * ss)))
    value_font = load_font(font_path, value_fs)
    label_font = load_font(font_path, label_fs)
    range_font = load_font(font_path, range_fs)
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    show_value = bool(cfg.get("show_value", True))
    show_label = bool(cfg.get("show_label", True))
    show_min = bool(cfg.get("show_min", True))
    show_max = bool(cfg.get("show_max", True))
    range_units = bool(cfg.get("range_units", False))
    grow_height = bool(cfg.get("grow_height", True))
    grow_start = _clamp01(float(cfg.get("grow_start", 0.55)))
    inactive_alpha = max(0, min(255, int(cfg.get("inactive_alpha", 95))))
    inactive = _rgba(cfg.get("inactive_color", "#3E3E3E"), (62, 62, 62), inactive_alpha)
    text_color = _rgba(cfg.get("text_color", "#FFFFFF"), (255, 255, 255), 255)
    dim_color = _rgba(cfg.get("range_color", "#E0E0E0"), (224, 224, 224), 255)
    raw_gradient = cfg.get(
        "gradient",
        ["#16A7AF", "#08B86B", "#13C630", "#C8D923", "#FFD42A", "#FF9A2E"],
    )
    if not isinstance(raw_gradient, (list, tuple)) or not raw_gradient:
        raw_gradient = ["#16A7AF", "#08B86B", "#13C630", "#C8D923", "#FFD42A", "#FF9A2E"]
    gradient_tuple = tuple(raw_gradient)

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    unit_for_value = str(cfg.get("value_unit", unit or ""))
    if formatted_val is not None:
        value_text = str(formatted_val)
    elif value is not None:
        value_text = _fmt_number(float(value), decimals)
        if show_value and bool(cfg.get("value_show_unit", True)) and unit_for_value:
            value_text = f"{value_text} {unit_for_value}"
    else:
        value_text = "--"

    value_h = _text_size(dd, value_text, value_font, text_stroke)[1] if show_value else 0
    label_h = _text_size(dd, str(label), label_font, text_stroke)[1] if show_label and label else 0
    sample_range = _fmt_number(max(abs(val_min), abs(val_max)), decimals)
    range_h = _text_size(dd, sample_range, range_font, text_stroke)[1] if (show_min or show_max) else 0

    pad_x = 4 * ss
    top_pad = 3 * ss
    value_gap = 3 * ss if value_h else 0
    bottom_text_h = max(label_h, range_h)
    bottom_pad = 3 * ss

    if "segment_height" in cfg:
        seg_area_h = max(8 * ss, int(round(float(cfg["segment_height"]) * ss)))
    else:
        seg_area_h = max(16 * ss, int(round(width * float(cfg.get("segment_height_ratio", 0.105)))))

    raster_w = width + pad_x * 2
    raster_h = int(top_pad + value_h + value_gap + seg_area_h + 5 * ss + bottom_text_h + bottom_pad)
    seg_top = top_pad + value_h + value_gap
    seg_bottom = seg_top + seg_area_h
    bottom_y = seg_bottom + 5 * ss

    total_gap = gap * (segments - 1)
    if total_gap >= width:
        gap = 0
        total_gap = 0
    seg_w = (width - total_gap) / segments

    if value is not None:
        frac = _fraction(float(value), val_min, val_max)
        active = 0 if frac <= 0.0 else min(segments, int(ceil(frac * segments - 1e-12)))
    else:
        active = 0

    # 1. Fetch or build static base layer
    base_key = _static_cache_key(
        "seg_base", font_path, raster_w, raster_h, ss, pad_x, top_pad, value_h, value_gap,
        seg_area_h, seg_top, seg_bottom, bottom_y, bottom_text_h, segments, gap, radius,
        round(seg_w, 2), grow_height, round(grow_start, 2), inactive, show_min, show_max, show_label,
        val_min, val_max, decimals, range_units, unit, label, range_fs, label_fs, text_stroke,
        dim_color, text_color, cfg.get("icon"), bool(cfg.get("uppercase_label", True))
    )
    base_img = _SEG_BASE_CACHE.get(base_key)
    if base_img is None:
        base_img = _build_seg_base_layer(
            raster_w, raster_h, ss, pad_x, top_pad, value_h, value_gap, seg_area_h,
            seg_top, seg_bottom, bottom_y, bottom_text_h, segments, gap, radius, seg_w,
            grow_height, grow_start, inactive, show_min, show_max, show_label, val_min,
            val_max, decimals, range_units, unit, label, font_path, range_fs, label_fs,
            text_stroke, dim_color, text_color, cfg.get("icon"), bool(cfg.get("uppercase_label", True))
        )
        _SEG_BASE_CACHE[base_key] = base_img

    # 2. Composite active segments & value text on top of base image copy
    out_img = base_img.copy()

    if active > 0:
        active_layer = _get_seg_active_layer(
            active, segments, raster_w, raster_h, ss, pad_x, seg_bottom, seg_area_h,
            gap, radius, seg_w, grow_height, grow_start, gradient_tuple
        )
        if active_layer:
            out_img.alpha_composite(active_layer)

    if show_value and value_text:
        d = ImageDraw.Draw(out_img)
        _draw_text_bounded(
            d, (pad_x, top_pad), value_text,
            font=value_font, fill=text_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor="la",
        )

    _STATIC_CACHE[cache_key] = out_img
    return out_img
