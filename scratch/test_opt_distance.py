import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import Any, Optional
from PIL import Image, ImageDraw

from src.indicators.helpers import (
    load_font, parse_hex_color, s, _BoundedStaticCache, _static_cache_key, _STATIC_CACHE
)
from src.indicators.bar import (
    _rgb, _rgba, _clamp01, _fraction, _fmt_number,
    _text_size, _draw_text_bounded, _line_with_shadow
)

# Text metrics cache for ruler
_RULER_METRICS_CACHE: dict[tuple, tuple[int, int, int]] = {}


def _get_ruler_text_metrics(
    font_path: str,
    title: str, title_font, show_title: bool,
    range_sample: str, range_font, show_range: bool,
    value_text: str, value_font, show_value: bool,
    text_stroke: int,
) -> tuple[int, int, int]:
    key = (font_path, title if show_title else "", range_sample if show_range else "", value_text if show_value else "", text_stroke)
    m = _RULER_METRICS_CACHE.get(key)
    if m is not None:
        return m

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    title_h = _text_size(dd, title, title_font, text_stroke)[1] if show_title and title else 0
    range_h = _text_size(dd, range_sample, range_font, text_stroke)[1] if show_range else 0
    value_h = _text_size(dd, value_text, value_font, text_stroke)[1] if show_value else 0

    if len(_RULER_METRICS_CACHE) > 256:
        _RULER_METRICS_CACHE.clear()
    _RULER_METRICS_CACHE[key] = (title_h, range_h, value_h)
    return title_h, range_h, value_h


def optimized_render_ruler(
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
    ticks: int,
    thickness: int,
    size_px: int,
    fs: int,
    outline: int,
    ss: int,
    formatted_val: str | None,
):
    ss = max(1, int(ss))
    width = max(80 * ss, int(size_px * ss))

    title_fs = max(8 * ss, int(round(float(cfg.get("title_font_scale", 1.00)) * fs * ss)))
    label_fs = max(7 * ss, int(round(float(cfg.get("range_font_scale", 0.82)) * fs * ss)))
    value_fs = max(8 * ss, int(round(float(cfg.get("value_font_scale", 1.00)) * fs * ss)))
    title_font = load_font(font_path, title_fs)
    range_font = load_font(font_path, label_fs)
    value_font = load_font(font_path, value_fs)
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    show_title = bool(cfg.get("show_label", True))
    show_range = bool(cfg.get("show_range_labels", True))
    show_mid = bool(cfg.get("show_mid_label", True))
    show_value = bool(cfg.get("show_value", False))
    range_units = bool(cfg.get("range_units", True))
    title_with_unit = bool(cfg.get("title_with_unit", True))
    uppercase_title = bool(cfg.get("uppercase_title", True))
    decimals = int(cfg.get("decimals", 0))

    raw_title = str(cfg.get("title_text", label or "")).strip()
    title = raw_title.upper() if uppercase_title else raw_title
    unit_title = str(unit or "").upper() if uppercase_title else str(unit or "")
    if show_title and title_with_unit and unit_title:
        title = f"{title} | {unit_title}" if title else unit_title

    val_num = float(value) if value is not None else 0.0
    if formatted_val is not None:
        value_text = str(formatted_val)
    elif value is not None:
        value_text = f"{_fmt_number(val_num, decimals)} {unit}".strip()
    else:
        value_text = "--"

    # Outer cache key for the whole finished ruler widget
    cache_key = _static_cache_key(
        "ruler_full", canvas_w, canvas_h, font_path,
        val_num if value is not None else None, value_text, unit, label,
        size_px, fs, outline, ss, val_min, val_max, ticks, thickness
    )
    cached = _STATIC_CACHE.get(cache_key)
    if cached is not None:
        return cached

    major_divisions = max(1, int(cfg.get("major_ticks", ticks if ticks > 0 else 8)))
    minor_per_major = max(1, int(cfg.get("minor_ticks", 5)))
    total_divisions = major_divisions * minor_per_major

    track_color = _rgba(cfg.get("track_color", "#F4F4F4"), (244, 244, 244), int(cfg.get("track_alpha", 235)))
    tick_color = _rgba(cfg.get("tick_color", "#F6F6F6"), (246, 246, 246), int(cfg.get("tick_alpha", 240)))
    marker_color = _rgba(cfg.get("marker_color", cfg.get("dot_color", "#159FA5")), (21, 159, 165), 255)
    marker_border = _rgba(cfg.get("marker_border_color", "#D8D8D8"), (216, 216, 216), 255)
    text_color = _rgba(cfg.get("text_color", "#F4F4F4"), (244, 244, 244), 255)
    dim_text = _rgba(cfg.get("range_color", cfg.get("text_color", "#E0E0E0")), (224, 224, 224), 255)

    line_w = max(1 * ss, int(round(max(1, thickness) * 0.35 * ss)))
    pixel_profile = str(cfg.get("tick_profile", "default")).strip().lower() == "pixel"
    tick_w = max(1 * ss, int(round(float(cfg.get("tick_width", 1.4)) * ss)))
    major_len = max(8 * ss, int(round(float(cfg.get("major_tick_length", 17)) * ss)))
    minor_len = max(4 * ss, int(round(float(cfg.get("minor_tick_length", 10)) * ss)))
    if pixel_profile:
        major_len = max(8 * ss, int(round(width * 0.040)))
        minor_len = max(4 * ss, int(round(width * 0.018)))
    marker_radius = max(3 * ss, int(round(float(cfg.get("marker_size", 7)) * ss)))
    marker_border_w = max(1 * ss, int(round(float(cfg.get("marker_border_width", 1.5)) * ss)))

    range_sample = f"{_fmt_number(max(abs(val_min), abs(val_max)), decimals)} {unit}".strip()
    title_h, range_h, value_h = _get_ruler_text_metrics(
        font_path, title, title_font, show_title,
        range_sample, range_font, show_range,
        value_text, value_font, show_value, text_stroke
    )

    pad_x = max(marker_radius + 4 * ss, 8 * ss)
    pad_top = 4 * ss
    title_gap = 5 * ss if title_h else 0
    value_gap = 4 * ss if value_h else 0
    track_y = pad_top + title_h + title_gap + value_h + value_gap + major_len + marker_radius
    bottom_gap = 6 * ss
    height = int(track_y + marker_radius + bottom_gap + range_h + 5 * ss)
    raster_w = width + pad_x * 2

    static_key = _static_cache_key(
        "bar_ruler_v2",
        raster_w, height, width, track_y,
        title, font_path, title_fs, label_fs, text_stroke,
        show_title, show_range, show_mid, range_units, decimals,
        val_min, val_max, unit, major_divisions, minor_per_major,
        track_color, tick_color, text_color, dim_text,
        line_w, tick_w, major_len, minor_len, pixel_profile, ss,
    )
    base = _STATIC_CACHE.get(static_key)
    if base is None:
        base = Image.new("RGBA", (raster_w, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(base)
        x1 = pad_x
        x2 = pad_x + width

        if show_title and title:
            _draw_text_bounded(
                d, (raster_w / 2, pad_top), title,
                font=title_font, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ma",
            )

        # Track + shadow.
        _line_with_shadow(d, (x1, track_y, x2, track_y), fill=track_color, width=line_w)

        # Ticks all extend upward from the track, matching the reference image.
        for i in range(total_divisions + 1):
            x = int(round(x1 + width * i / total_divisions))
            is_major = (i % minor_per_major) == 0
            length = major_len if is_major else minor_len
            _line_with_shadow(
                d, (x, track_y - length, x, track_y + max(1 * ss, line_w // 2)),
                fill=tick_color,
                width=(max(tick_w, 2 * ss) if is_major else tick_w) if not pixel_profile
                else (max(2 * ss, int(round(tick_w * 1.25))) if is_major
                      else max(1 * ss, int(round(tick_w * 0.65)))),
            )

        if show_range:
            def range_text(v: float) -> str:
                txt = _fmt_number(v, decimals)
                return f"{txt} {unit}".strip() if range_units else txt

            y = track_y + marker_radius + bottom_gap
            left = range_text(val_min)
            mid = range_text((val_min + val_max) * 0.5)
            right = range_text(val_max)
            _draw_text_bounded(
                d, (pad_x, y), left, font=range_font, fill=dim_text,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="la",
            )
            if show_mid:
                _draw_text_bounded(
                    d, (raster_w / 2, y), mid, font=range_font, fill=dim_text,
                    stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                    bounds=(raster_w, height), anchor="ma",
                )
            _draw_text_bounded(
                d, (raster_w - pad_x, y), right, font=range_font, fill=dim_text,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ra",
            )
        _STATIC_CACHE[static_key] = base

    img = base.copy()
    d = ImageDraw.Draw(img)

    if value is not None:
        frac = _fraction(val_num, val_min, val_max)
        marker_x = int(round(pad_x + frac * width))

        # Marker shadow, border and fill.
        shadow_r = marker_radius + marker_border_w
        d.ellipse(
            (marker_x - shadow_r + 2 * ss, track_y - shadow_r + 2 * ss,
             marker_x + shadow_r + 2 * ss, track_y + shadow_r + 2 * ss),
            fill=(0, 0, 0, 130),
        )
        d.ellipse(
            (marker_x - marker_radius - marker_border_w, track_y - marker_radius - marker_border_w,
             marker_x + marker_radius + marker_border_w, track_y + marker_radius + marker_border_w),
            fill=marker_border,
        )
        d.ellipse(
            (marker_x - marker_radius, track_y - marker_radius,
             marker_x + marker_radius, track_y + marker_radius),
            fill=marker_color,
        )

        if show_value and value_text:
            value_y = pad_top + title_h + (title_gap if title_h else 0)
            value_offset_x = int(round(float(cfg.get("value_offset_x", 0.0)) * canvas_w / 100.0 * ss))
            value_offset_y = int(round(float(cfg.get("value_offset_y", 0.0)) * canvas_h / 100.0 * ss))
            _draw_text_bounded(
                d, (marker_x + value_offset_x, value_y + value_offset_y), value_text,
                font=value_font, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ma",
            )

    _STATIC_CACHE[cache_key] = img
    return img
