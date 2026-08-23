import sys
import json
import time
from pathlib import Path
from math import ceil, floor
from PIL import Image, ImageDraw, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.indicators.bar as bar_mod
from src.indicators.helpers import _BoundedStaticCache, load_font, _static_cache_key, parse_hex_color
from src.indicators.bar import _rgb, _rgba, _get_ruler_text_metrics

_TEXT_TILE_CACHE = _BoundedStaticCache(max_entries=256)
_SLOPE_BASE_CACHE = _BoundedStaticCache(max_entries=32)
_RULER_BASE_CACHE = _BoundedStaticCache(max_entries=64)

def _draw_text_bounded_cached(
    target_img: Image.Image,
    xy: tuple[float, float],
    text: str,
    *,
    font,
    font_path: str,
    fill,
    stroke_width: int,
    stroke_fill,
    bounds: tuple[int, int],
    anchor: str = "la",
) -> None:
    if not text:
        return
    text_str = str(text)
    f_size = getattr(font, "size", 0)
    tile_key = (
        text_str, font_path, f_size,
        tuple(fill) if isinstance(fill, (tuple, list)) else fill,
        stroke_width,
        tuple(stroke_fill) if isinstance(stroke_fill, (tuple, list)) else stroke_fill,
        anchor,
    )
    tile_data = _TEXT_TILE_CACHE.get(tile_key)
    if tile_data is None:
        dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        d_dum = ImageDraw.Draw(dummy)
        try:
            box = d_dum.textbbox((0, 0), text_str, font=font, anchor=anchor, stroke_width=stroke_width)
        except TypeError:
            box = d_dum.textbbox((0, 0), text_str, font=font, stroke_width=stroke_width)
        tw = max(1, box[2] - box[0])
        th = max(1, box[3] - box[1])
        tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        d_tile = ImageDraw.Draw(tile)
        try:
            d_tile.text((-box[0], -box[1]), text_str, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, anchor=anchor)
        except TypeError:
            d_tile.text((-box[0], -box[1]), text_str, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        tile_data = (tile, box[0], box[1], box[2], box[3], tw, th)
        _TEXT_TILE_CACHE[tile_key] = tile_data

    tile, b0, b1, b2, b3, tw, th = tile_data
    x, y = float(xy[0]), float(xy[1])
    w, h = bounds
    dx = 0.0
    dy = 0.0
    real_x0 = x + b0
    real_x1 = x + b2
    real_y0 = y + b1
    real_y1 = y + b3
    if real_x0 < 0:
        dx = -real_x0
    elif real_x1 > w:
        dx = w - real_x1
    if real_y0 < 0:
        dy = -real_y0
    elif real_y1 > h:
        dy = h - real_y1

    dest_x = int(round(x + b0 + dx))
    dest_y = int(round(y + b1 + dy))
    target_img.alpha_composite(tile, (dest_x, dest_y))


def _opt_render_slope(
    *,
    canvas_w: int,
    canvas_h: int,
    font_path: str,
    value: float,
    unit: str,
    label: str,
    cfg: dict,
    val_min: float,
    val_max: float,
    thickness: int,
    size_px: int,
    fs: int,
    outline: int,
    ss: int,
    formatted_val: str | None,
):
    ss = max(1, int(ss))
    lo = float(val_min)
    hi = float(val_max)
    if hi <= lo:
        hi = lo + 1.0

    decimals = max(0, int(cfg.get("decimals", 1)))
    show_label = bool(cfg.get("show_label", True))
    show_value = bool(cfg.get("show_value", True))
    show_range = bool(cfg.get("show_range_labels", True))
    missing = bool(cfg.get("_slope_missing", False))
    opacity = max(0.0, min(1.0, float(cfg.get("opacity", 1.0))))
    major_tick = max(0.1, abs(float(cfg.get("major_tick", 5.0))))
    minor_tick = max(0.1, abs(float(cfg.get("minor_tick", 1.0))))
    if minor_tick > major_tick:
        minor_tick = major_tick

    title_fs = max(8 * ss, int(round(fs * 0.9 * ss)))
    tick_fs = max(7 * ss, int(round(fs * 0.72 * ss)))
    value_fs = max(9 * ss, int(round(fs * 1.12 * ss)))
    title_font = load_font(font_path, title_fs)
    tick_font = load_font(font_path, tick_fs)
    value_font = load_font(font_path, value_fs)
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    title = str(cfg.get("title_text", label or "SLOPE")).strip()
    if bool(cfg.get("uppercase_label", True)):
        title = title.upper()
    value_text = (
        str(formatted_val)
        if formatted_val is not None
        else ("--%" if missing else f"{bar_mod._format_slope_number(value, decimals)}%")
    )

    track_color = _rgba(cfg.get("track_color", "#8D9AA7"), (141, 154, 167), int(235 * opacity))
    tick_color = _rgba(cfg.get("tick_color", "#DDE7F2"), (221, 231, 242), int(240 * opacity))
    zero_color = _rgba(cfg.get("zero_tick_color", "#FFFFFF"), (255, 255, 255), int(255 * opacity))
    marker_color = _rgba(cfg.get("marker_color", "#FFD42A"), (255, 212, 42), int(255 * opacity))
    marker_border = _rgba(cfg.get("marker_border_color", "#FFFFFF"), (255, 255, 255), int(255 * opacity))
    text_color = _rgba(cfg.get("text_color", "#FFFFFF"), (255, 255, 255), int(255 * opacity))
    dim_color = _rgba(cfg.get("range_color", "#DDE7F2"), (221, 231, 242), int(235 * opacity))
    shadow_alpha = int(150 * opacity)

    track_height = max(200 * ss, int(size_px * ss))
    track_width = max(2 * ss, int(round(float(cfg.get("track_width", max(1, thickness * 0.45)) * ss))))
    pixel_profile = str(cfg.get("tick_profile", "default")).strip().lower() == "pixel"
    tick_width = max(1 * ss, int(round(float(cfg.get("tick_width", max(1, thickness))) * ss)))
    major_len = max(10 * ss, int(round(float(cfg.get("major_tick_length", 22.0)) * ss)))
    minor_len = max(5 * ss, int(round(float(cfg.get("minor_tick_length", 12.0)) * ss)))
    marker_width = max(1 * ss, int(round(float(cfg.get("marker_width", 3.0)) * ss)))
    if pixel_profile:
        major_len = max(10 * ss, int(round(track_height * 0.075)))
        minor_len = max(5 * ss, int(round(track_height * 0.038)))
        marker_width = max(marker_width, 4 * ss)
    marker_len = max(12 * ss, int(round(float(cfg.get("marker_length", 28.0)) * ss)))
    marker_radius = max(3 * ss, int(round(float(cfg.get("marker_size", 6.0)) * ss)))

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    value_width = bar_mod._text_size(dd, value_text, value_font, text_stroke)[0] if show_value else 0

    static_key = _static_cache_key(
        "bar_slope_base_v2", font_path,
        title, title_fs, tick_fs, value_fs, text_stroke,
        show_label, show_range, show_value, lo, hi, major_tick, minor_tick,
        track_color, tick_color, zero_color, text_color, dim_color,
        track_width, tick_width, major_len, minor_len, marker_width,
        marker_len, marker_radius, marker_color, marker_border,
        shadow_alpha, pixel_profile, ss, opacity, size_px, value_width,
    )
    base_data = _SLOPE_BASE_CACHE.get(static_key)
    if base_data is None:
        tick_values = []
        tick_start = ceil((lo - 1e-9) / minor_tick) * minor_tick
        tick_count = int(floor((hi - tick_start + 1e-9) / minor_tick))
        for index in range(max(0, tick_count + 1)):
            tick = tick_start + index * minor_tick
            if lo - 1e-7 <= tick <= hi + 1e-7:
                tick_values.append(0.0 if abs(tick) < 1e-7 else tick)
        if not tick_values:
            tick_values = [lo, 0.0 if lo <= 0.0 <= hi else hi]

        major_values = [
            tick for tick in tick_values
            if abs(tick / major_tick - round(tick / major_tick)) < 1e-6
            or abs(tick) < 1e-7
        ]
        if show_range:
            tick_texts = [bar_mod._format_slope_number(tick, 0) for tick in major_values]
        else:
            tick_texts = []
        tick_widths = [
            bar_mod._text_size(dd, text, tick_font, text_stroke)[0] for text in tick_texts
        ]
        label_width = max(tick_widths or [0])
        title_width = bar_mod._text_size(dd, title, title_font, text_stroke)[0] if show_label else 0

        pad_x = 8 * ss
        pad_top = 5 * ss
        title_gap = 5 * ss if show_label and title else 0
        title_h = bar_mod._text_size(dd, title, title_font, text_stroke)[1] if show_label else 0
        track_x = pad_x + label_width + major_len + 10 * ss
        top = pad_top + title_h + title_gap
        bottom = top + track_height
        value_x = track_x + marker_len + 12 * ss
        raster_w = max(track_x + track_width + pad_x, value_x + value_width + pad_x)
        raster_h = bottom + 6 * ss

        base = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(base)
        if show_label and title:
            bar_mod._draw_text_bounded(
                d, (raster_w / 2, pad_top), title,
                font=title_font, fill=text_color, stroke_width=text_stroke,
                stroke_fill=(0, 0, 0, 230), bounds=(raster_w, raster_h), anchor="ma",
            )
        d.line(
            (track_x, top, track_x, bottom), fill=(0, 0, 0, shadow_alpha),
            width=max(track_width + 2 * ss, 1),
        )
        d.line((track_x, top, track_x, bottom), fill=track_color, width=track_width)
        for tick in tick_values:
            fraction = bar_mod._fraction(hi - tick, 0.0, hi - lo)
            y = int(round(top + fraction * track_height))
            is_zero = abs(tick) < 1e-7
            is_major = is_zero or abs(tick / major_tick - round(tick / major_tick)) < 1e-6
            length = major_len if is_major else minor_len
            colour = zero_color if is_zero else (tick_color if is_major else dim_color)
            d.line(
                (track_x - length, y, track_x + max(1, track_width // 2), y),
                fill=(0, 0, 0, shadow_alpha), width=max(tick_width + ss, 1),
            )
            d.line(
                (track_x - length, y, track_x + max(1, track_width // 2), y),
                fill=colour,
                width=max(
                    tick_width + (ss if is_zero else 0), 1
                ) if not pixel_profile else max(
                    (tick_width + 2 * ss) if is_zero else
                    (int(round(tick_width * 1.25)) if is_major else max(1 * ss, int(round(tick_width * 0.65)))),
                    1,
                ),
            )
            if show_range and is_major:
                tick_text = bar_mod._format_slope_number(tick, 0)
                bar_mod._draw_text_bounded(
                    d, (track_x - length - 6 * ss, y), tick_text,
                    font=tick_font, fill=zero_color if is_zero else dim_color,
                    stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                    bounds=(raster_w, raster_h), anchor="rm",
                )
        base_data = (
            base, track_x, top, bottom, track_height, value_x, raster_w, raster_h,
            marker_len, marker_width, marker_color, marker_border, marker_radius,
            pixel_profile, shadow_alpha, text_color, text_stroke, value_font, ss, lo, hi, show_value
        )
        _SLOPE_BASE_CACHE[static_key] = base_data

    (
        base, track_x, top, bottom, track_height, value_x, raster_w, raster_h,
        marker_len, marker_width, marker_color, marker_border, marker_radius,
        pixel_profile, shadow_alpha, text_color, text_stroke, value_font, ss, lo, hi, show_value
    ) = base_data

    img = base.copy()
    d = ImageDraw.Draw(img)
    visual_value = max(lo, min(hi, float(value)))
    marker_fraction = bar_mod._fraction(hi - visual_value, 0.0, hi - lo)
    marker_y = int(round(top + marker_fraction * track_height))

    if not missing:
        d.line(
            (track_x - marker_len, marker_y, track_x + marker_len, marker_y),
            fill=(0, 0, 0, shadow_alpha), width=marker_width + 2 * ss,
        )
        d.line(
            (track_x - marker_len, marker_y, track_x + marker_len, marker_y),
            fill=marker_color, width=marker_width,
        )
        radius = marker_radius
        if pixel_profile:
            d.rectangle(
                (track_x - radius, marker_y - radius, track_x + radius, marker_y + radius),
                fill=marker_border,
            )
            inner = max(1, radius - max(1, ss))
            d.rectangle(
                (track_x - inner, marker_y - inner, track_x + inner, marker_y + inner),
                fill=marker_color,
            )
        else:
            d.ellipse(
                (track_x - radius, marker_y - radius, track_x + radius, marker_y + radius),
                fill=marker_border,
            )
            inner = max(1, radius - max(1, ss))
            d.ellipse(
                (track_x - inner, marker_y - inner, track_x + inner, marker_y + inner),
                fill=marker_color,
            )
    if show_value:
        _draw_text_bounded_cached(
            img, (value_x, marker_y), value_text,
            font=value_font, font_path=font_path, fill=text_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
            bounds=(raster_w, raster_h), anchor="lm",
        )
    return img


def _opt_render_ruler(
    *,
    canvas_w: int,
    canvas_h: int,
    font_path: str,
    value: float | None,
    unit: str,
    label: str,
    cfg: dict,
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
        value_text = f"{bar_mod._fmt_number(val_num, decimals)} {unit}".strip()
    else:
        value_text = "--"

    major_step = cfg.get("major_step")
    if major_step is None:
        unit_str = str(unit or "").strip().lower()
        lbl_str = str(label or "").strip().lower()
        if unit_str == "km" or "distance" in lbl_str or "dist" in lbl_str:
            major_step = 1.0
        elif unit_str in ("°c", "c", "degc") or "temperature" in lbl_str or "temp" in lbl_str:
            major_step = 1.0

    if major_step is not None and float(major_step) > 0 and abs(val_max - val_min) > 0:
        major_divisions = max(1, int(round(abs(val_max - val_min) / float(major_step))))
    else:
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

    range_sample = f"{bar_mod._fmt_number(max(abs(val_min), abs(val_max)), decimals)} {unit}".strip()
    title_h, range_h, value_h = _get_ruler_text_metrics(
        font_path, title, title_font, show_title,
        range_sample, range_font, show_range,
        value_text, value_font, show_value, text_stroke,
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
        "bar_ruler_v3",
        raster_w, height, width, track_y, pad_x, pad_top,
        title, font_path, title_fs, label_fs, value_fs, text_stroke,
        show_title, show_range, show_mid, show_value, range_units, decimals,
        val_min, val_max, unit, major_divisions, minor_per_major, major_step,
        track_color, tick_color, text_color, dim_text, marker_color, marker_border,
        marker_radius, marker_border_w, line_w, tick_w, major_len, minor_len,
        pixel_profile, ss, title_h, title_gap, value_h, value_gap,
    )
    base_data = _RULER_BASE_CACHE.get(static_key)
    if base_data is None:
        base = Image.new("RGBA", (raster_w, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(base)
        x1 = pad_x
        x2 = pad_x + width

        if show_title and title:
            bar_mod._draw_text_bounded(
                d, (raster_w / 2, pad_top), title,
                font=title_font, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ma",
            )

        # Track + shadow.
        bar_mod._line_with_shadow(d, (x1, track_y, x2, track_y), fill=track_color, width=line_w)

        # Ticks
        if major_step is not None and float(major_step) > 0 and abs(val_max - val_min) > 0:
            step = float(major_step)
            minor_step = step / minor_per_major
            k_min = int(floor(val_min / minor_step - 1e-7))
            k_max = int(ceil(val_max / minor_step + 1e-7))
            for k in range(k_min, k_max + 1):
                v = round(k * minor_step, 9)
                if val_min - 1e-7 <= v <= val_max + 1e-7:
                    frac = (v - val_min) / (val_max - val_min)
                    x = int(round(x1 + width * frac))
                    m_k = round(v / step)
                    is_major = abs(m_k * step - v) < 1e-6
                    length = major_len if is_major else minor_len
                    bar_mod._line_with_shadow(
                        d, (x, track_y - length, x, track_y + max(1 * ss, line_w // 2)),
                        fill=tick_color,
                        width=(max(tick_w, 2 * ss) if is_major else tick_w) if not pixel_profile
                        else (max(2 * ss, int(round(tick_w * 1.25))) if is_major
                              else max(1 * ss, int(round(tick_w * 0.65)))),
                    )
        else:
            for i in range(total_divisions + 1):
                x = int(round(x1 + width * i / total_divisions))
                is_major = (i % minor_per_major) == 0
                length = major_len if is_major else minor_len
                bar_mod._line_with_shadow(
                    d, (x, track_y - length, x, track_y + max(1 * ss, line_w // 2)),
                    fill=tick_color,
                    width=(max(tick_w, 2 * ss) if is_major else tick_w) if not pixel_profile
                    else (max(2 * ss, int(round(tick_w * 1.25))) if is_major
                          else max(1 * ss, int(round(tick_w * 0.65)))),
                )

        if show_range:
            def range_text(v: float) -> str:
                txt = bar_mod._fmt_number(v, decimals)
                return f"{txt} {unit}".strip() if range_units else txt

            y = track_y + marker_radius + bottom_gap
            left = range_text(val_min)
            mid = range_text((val_min + val_max) * 0.5)
            right = range_text(val_max)
            bar_mod._draw_text_bounded(
                d, (pad_x, y), left, font=range_font, fill=dim_text,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="la",
            )
            if show_mid:
                bar_mod._draw_text_bounded(
                    d, (raster_w / 2, y), mid, font=range_font, fill=dim_text,
                    stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                    bounds=(raster_w, height), anchor="ma",
                )
            bar_mod._draw_text_bounded(
                d, (raster_w - pad_x, y), right, font=range_font, fill=dim_text,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ra",
            )
        base_data = (
            base, pad_x, width, track_y, marker_radius, marker_border_w, marker_border,
            marker_color, show_value, title_h, title_gap, pad_top, value_font, text_color,
            text_stroke, raster_w, height, ss, val_min, val_max
        )
        _RULER_BASE_CACHE[static_key] = base_data

    (
        base, pad_x, width, track_y, marker_radius, marker_border_w, marker_border,
        marker_color, show_value, title_h, title_gap, pad_top, value_font, text_color,
        text_stroke, raster_w, height, ss, val_min, val_max
    ) = base_data

    img = base.copy()
    d = ImageDraw.Draw(img)

    if value is not None:
        frac = bar_mod._fraction(val_num, val_min, val_max)
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
            _draw_text_bounded_cached(
                img, (marker_x + value_offset_x, value_y + value_offset_y), value_text,
                font=value_font, font_path=font_path, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ma",
            )

    return img


with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    v10 = json.load(f)

print("--- Testing Byte-Exact Pixel Parity for Altitude ---")
alt_cfg = dict(v10["indicators"]["alt_visual"])
for frac, test_val in [(0.0, 0.0), (0.25, 250.0), (0.50, 500.0), (0.75, 750.0), (1.0, 1000.0), (None, None)]:
    orig = bar_mod._render_ruler(
        canvas_w=1280, canvas_h=720, font_path="", value=test_val, unit="m", label="ALTITUDE",
        cfg=alt_cfg, val_min=0.0, val_max=1000.0, ticks=5, thickness=1, size_px=115, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    opt = _opt_render_ruler(
        canvas_w=1280, canvas_h=720, font_path="", value=test_val, unit="m", label="ALTITUDE",
        cfg=alt_cfg, val_min=0.0, val_max=1000.0, ticks=5, thickness=1, size_px=115, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    diff = ImageChops.difference(orig, opt)
    bbox = diff.getbbox()
    print(f"Alt val={test_val}: diff bbox = {bbox}")
    assert bbox is None, f"Parity failed for Alt val={test_val}"

print("ALTITUDE PIXEL PARITY VERIFIED: 100% BYTE EXACT!")

slope_cfg = dict(v10["indicators"]["slope_text"])
print("\n--- Testing Byte-Exact Pixel Parity for Slope ---")
for test_val in [-12.0, -5.0, 0.0, 3.7, 10.0, None]:
    cfg_test = dict(slope_cfg)
    if test_val is None:
        cfg_test["_slope_missing"] = True
    v = 0.0 if test_val is None else test_val
    orig = bar_mod._render_slope(
        canvas_w=1280, canvas_h=720, font_path="", value=v, unit="%", label="SLOPE",
        cfg=cfg_test, val_min=-20.0, val_max=20.0, thickness=2, size_px=108, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    opt = _opt_render_slope(
        canvas_w=1280, canvas_h=720, font_path="", value=v, unit="%", label="SLOPE",
        cfg=cfg_test, val_min=-20.0, val_max=20.0, thickness=2, size_px=108, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    diff = ImageChops.difference(orig, opt)
    bbox = diff.getbbox()
    print(f"Slope val={test_val}: diff bbox = {bbox}")
    assert bbox is None, f"Parity failed for Slope val={test_val}"

print("SLOPE PIXEL PARITY VERIFIED: 100% BYTE EXACT!")
