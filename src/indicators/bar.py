"""TeleM bar indicator rendering.

Two visual styles are handled by the same renderer:

``ruler``
    Continuous telemetry ruler similar to the Telemetry Overlay distance bar:
    dense minor/major ticks, a circular position marker, title and range labels.

``segments``
    Segmented colour bar suitable for battery/solar/etc. Active segments can use
    a multi-stop gradient while inactive segments stay dimmed.

The public entry point intentionally keeps TeleM's existing
``_render_bar_indicator`` signature, so the module can replace the current
``src/indicators/bar.py`` without changing the dispatcher.  To use the segment
style while still dispatching as ``form='bar'``, set ``bar_style='segments'``.

The renderer is resolution independent and supersample-safe.  All text that is
part of the bar is drawn inside the local raster so it cannot be clipped later
by the compositor's annotation path.
"""

from __future__ import annotations

from math import ceil, floor
from typing import Any, Iterable

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - TeleM requires Pillow at runtime
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import (
    _STATIC_CACHE,
    _static_cache_key,
    load_font,
    parse_hex_color,
    s,
)
from src.indicators.icons import render_icon


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _rgb(value: Any, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    c = parse_hex_color(value) if isinstance(value, str) else None
    return c or fallback


def _rgba(value: Any, fallback: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = _rgb(value, fallback)
    return r, g, b, max(0, min(255, int(alpha)))


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _fraction(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return _clamp01((float(value) - lo) / (hi - lo))


def _fmt_number(value: float, decimals: int) -> str:
    if decimals <= 0:
        return f"{value:.0f}"
    return f"{value:.{decimals}f}"


def _gradient_colour(stops: Iterable[Any], position: float) -> tuple[int, int, int]:
    colours = [_rgb(x, (255, 255, 255)) for x in stops]
    if not colours:
        colours = [(0, 220, 170), (0, 190, 50), (245, 225, 30), (255, 145, 35)]
    if len(colours) == 1:
        return colours[0]

    p = _clamp01(position)
    scaled = p * (len(colours) - 1)
    idx = min(len(colours) - 2, int(scaled))
    t = scaled - idx
    a = colours[idx]
    b = colours[idx + 1]
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def _text_size(draw: ImageDraw.ImageDraw, text: str, font, stroke: int = 0) -> tuple[int, int, tuple[int, int, int, int]]:
    box = draw.textbbox((0, 0), str(text), font=font, stroke_width=max(0, stroke))
    return max(0, box[2] - box[0]), max(0, box[3] - box[1]), box


def _draw_text_bounded(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    *,
    font,
    fill,
    stroke_width: int,
    stroke_fill,
    bounds: tuple[int, int],
    anchor: str = "la",
) -> None:
    """Draw text but clamp its real glyph bbox inside ``bounds``.

    Pillow anchors are convenient, but TrueType ascent/descent + stroke can
    still cross the raster edge.  We first ask Pillow for the actual bbox at the
    requested anchor and translate the origin just enough to keep it contained.
    """
    x, y = float(xy[0]), float(xy[1])
    try:
        box = draw.textbbox((x, y), str(text), font=font, anchor=anchor, stroke_width=stroke_width)
    except TypeError:  # old Pillow fallback
        box = draw.textbbox((x, y), str(text), font=font, stroke_width=stroke_width)
        anchor = None  # type: ignore[assignment]

    w, h = bounds
    dx = 0.0
    dy = 0.0
    if box[0] < 0:
        dx = -box[0]
    elif box[2] > w:
        dx = w - box[2]
    if box[1] < 0:
        dy = -box[1]
    elif box[3] > h:
        dy = h - box[3]

    kwargs = dict(font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    if anchor is not None:
        kwargs["anchor"] = anchor
    draw.text((x + dx, y + dy), str(text), **kwargs)


def _line_with_shadow(draw, xy, *, fill, width: int, shadow: bool = True) -> None:
    if shadow:
        draw.line(xy, fill=(0, 0, 0, 170), width=max(1, width + 2))
    draw.line(xy, fill=fill, width=max(1, width))


# ---------------------------------------------------------------------------
# Ruler / continuous bar
# ---------------------------------------------------------------------------


def _render_ruler(
    *,
    canvas_w: int,
    canvas_h: int,
    font_path: str,
    value: float,
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

    # Fonts are loaded at supersampled size; the dispatcher-provided ``font``
    # is output-size and would become too small when ss > 1.
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

    # Dense ruler: ``ticks`` remains the major division count for backwards
    # compatibility; ``minor_ticks`` controls subdivisions between majors.
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

    # Measure text to create a clipping-safe visual rectangle.
    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    title_h = _text_size(dd, title, title_font, text_stroke)[1] if show_title and title else 0
    range_sample = f"{_fmt_number(max(abs(val_min), abs(val_max)), decimals)} {unit}".strip()
    range_h = _text_size(dd, range_sample, range_font, text_stroke)[1] if show_range else 0
    value_text = formatted_val if formatted_val is not None else f"{_fmt_number(value, decimals)} {unit}".strip()
    value_h = _text_size(dd, value_text, value_font, text_stroke)[1] if show_value else 0

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
    frac = _fraction(value, val_min, val_max)
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

    return img


# ---------------------------------------------------------------------------
# Segmented bar
# ---------------------------------------------------------------------------


def _render_segments(
    *,
    canvas_w: int,
    canvas_h: int,
    font_path: str,
    value: float,
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
    gradient = cfg.get(
        "gradient",
        ["#16A7AF", "#08B86B", "#13C630", "#C8D923", "#FFD42A", "#FF9A2E"],
    )
    if not isinstance(gradient, (list, tuple)) or not gradient:
        gradient = ["#16A7AF", "#08B86B", "#13C630", "#C8D923", "#FFD42A", "#FF9A2E"]

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    unit_for_value = str(cfg.get("value_unit", unit or ""))
    if formatted_val is not None:
        # TeleM's compositor usually passes an already formatted value, often
        # including the unit.  Never append the unit a second time.
        value_text = str(formatted_val)
    else:
        value_text = _fmt_number(value, decimals)
        if show_value and bool(cfg.get("value_show_unit", True)) and unit_for_value:
            value_text = f"{value_text} {unit_for_value}"
    value_h = _text_size(dd, value_text, value_font, text_stroke)[1] if show_value else 0
    label_h = _text_size(dd, str(label), label_font, text_stroke)[1] if show_label and label else 0
    sample_range = _fmt_number(max(abs(val_min), abs(val_max)), decimals)
    range_h = _text_size(dd, sample_range, range_font, text_stroke)[1] if (show_min or show_max) else 0

    pad_x = 4 * ss
    top_pad = 3 * ss
    value_gap = 3 * ss if value_h else 0
    bottom_text_h = max(label_h, range_h)
    bottom_pad = 3 * ss

    # Allow explicit segment height but default it from the visual width so the
    # proportions remain stable between 1080p and 4K.
    if "segment_height" in cfg:
        seg_area_h = max(8 * ss, int(round(float(cfg["segment_height"]) * ss)))
    else:
        seg_area_h = max(16 * ss, int(round(width * float(cfg.get("segment_height_ratio", 0.105)))))

    raster_w = width + pad_x * 2
    raster_h = int(top_pad + value_h + value_gap + seg_area_h + 5 * ss + bottom_text_h + bottom_pad)
    seg_top = top_pad + value_h + value_gap
    seg_bottom = seg_top + seg_area_h

    total_gap = gap * (segments - 1)
    if total_gap >= width:
        gap = 0
        total_gap = 0
    seg_w = (width - total_gap) / segments
    frac = _fraction(value, val_min, val_max)
    # ceil makes the first non-zero value visible; exact zero still shows none.
    active = 0 if frac <= 0.0 else min(segments, int(ceil(frac * segments - 1e-12)))

    img = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    for i in range(segments):
        p = i / max(1, segments - 1)
        h_mult = grow_start + (1.0 - grow_start) * p if grow_height else 1.0
        sh = max(2 * ss, int(round(seg_area_h * h_mult)))
        x1 = int(round(pad_x + i * (seg_w + gap)))
        x2 = int(round(pad_x + i * (seg_w + gap) + seg_w - 1))
        y2 = seg_bottom
        y1 = y2 - sh
        colour = _gradient_colour(gradient, p)
        fill = (*colour, 255) if i < active else inactive

        # Subtle shadow improves readability on video without a blur pass.
        shadow_off = max(1, ss)
        d.rounded_rectangle(
            (x1 + shadow_off, y1 + shadow_off, x2 + shadow_off, y2 + shadow_off),
            radius=radius, fill=(0, 0, 0, 75),
        )
        d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill)

    if show_value and value_text:
        _draw_text_bounded(
            d, (pad_x, top_pad), value_text,
            font=value_font, fill=text_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor="la",
        )

    bottom_y = seg_bottom + 5 * ss
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

    if show_label and label:
        icon = render_icon(cfg.get("icon"), max(10 * ss, int(label_fs * 1.1)))
        if icon:
            ix = max(0, int((raster_w - icon.width - int(label_font.getlength(str(label)))) / 2) - 3 * ss)
            iy = max(0, int(bottom_y + (bottom_text_h - icon.height) / 2))
            img.alpha_composite(icon, (ix, iy))
        _draw_text_bounded(
            d, (raster_w / 2, bottom_y), str(label).upper() if cfg.get("uppercase_label", True) else str(label),
            font=label_font, fill=text_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor="ma",
        )

    return img


# ---------------------------------------------------------------------------
# Slope / grade vertical ruler
# ---------------------------------------------------------------------------


def _format_slope_number(value: float, decimals: int) -> str:
    """Format a slope value with an explicit sign for climb/descent."""
    return f"{float(value):+.{max(0, int(decimals))}f}"


def _render_slope(
    *,
    canvas_w: int,
    canvas_h: int,
    font_path: str,
    value: float,
    unit: str,
    label: str,
    cfg: dict[str, Any],
    val_min: float,
    val_max: float,
    thickness: int,
    size_px: int,
    fs: int,
    outline: int,
    ss: int,
    formatted_val: str | None,
):
    """Render the canonical ``slope`` value as a lightweight vertical ruler.

    ``value`` is already resolved telemetry.  This function only maps it to
    the configured visual range; it never reads altitude, distance or source
    data and never changes the canonical value used for the text label.
    """
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

    title_font = load_font(font_path, max(8 * ss, int(round(fs * 0.9 * ss))))
    tick_font = load_font(font_path, max(7 * ss, int(round(fs * 0.72 * ss))))
    value_font = load_font(font_path, max(9 * ss, int(round(fs * 1.12 * ss))))
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    title = str(cfg.get("title_text", label or "SLOPE")).strip()
    if bool(cfg.get("uppercase_label", True)):
        title = title.upper()
    value_text = (
        str(formatted_val)
        if formatted_val is not None
        else ("--%" if missing else f"{_format_slope_number(value, decimals)}%")
    )

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    tick_values: list[float] = []
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
        tick_texts = [_format_slope_number(tick, 0) for tick in major_values]
    else:
        tick_texts = []
    tick_widths = [
        _text_size(dd, text, tick_font, text_stroke)[0] for text in tick_texts
    ]
    label_width = max(tick_widths or [0])
    title_width = _text_size(dd, title, title_font, text_stroke)[0] if show_label else 0
    value_width = _text_size(dd, value_text, value_font, text_stroke)[0] if show_value else 0

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
    pad_x = 8 * ss
    pad_top = 5 * ss
    title_gap = 5 * ss if show_label and title else 0
    title_h = _text_size(dd, title, title_font, text_stroke)[1] if show_label else 0
    value_gap = 8 * ss if show_value else 0
    track_x = pad_x + label_width + major_len + 10 * ss
    top = pad_top + title_h + title_gap
    bottom = top + track_height
    value_x = track_x + marker_len + 12 * ss
    raster_w = max(track_x + track_width + pad_x, value_x + value_width + pad_x)
    raster_h = bottom + 6 * ss
    track_color = _rgba(cfg.get("track_color", "#8D9AA7"), (141, 154, 167), int(235 * opacity))
    tick_color = _rgba(cfg.get("tick_color", "#DDE7F2"), (221, 231, 242), int(240 * opacity))
    zero_color = _rgba(cfg.get("zero_tick_color", "#FFFFFF"), (255, 255, 255), int(255 * opacity))
    marker_color = _rgba(cfg.get("marker_color", "#FFD42A"), (255, 212, 42), int(255 * opacity))
    marker_border = _rgba(cfg.get("marker_border_color", "#FFFFFF"), (255, 255, 255), int(255 * opacity))
    text_color = _rgba(cfg.get("text_color", "#FFFFFF"), (255, 255, 255), int(255 * opacity))
    dim_color = _rgba(cfg.get("range_color", "#DDE7F2"), (221, 231, 242), int(235 * opacity))
    shadow_alpha = int(150 * opacity)

    static_key = _static_cache_key(
        "bar_slope_v1", raster_w, raster_h, track_x, top, bottom,
        title, font_path, title_font.size, tick_font.size, value_font.size,
        show_label, show_range, lo, hi, major_tick, minor_tick,
        track_color, tick_color, zero_color, text_color, dim_color,
        track_width, tick_width, major_len, minor_len, marker_width, pixel_profile, text_stroke,
    )
    base = _STATIC_CACHE.get(static_key)
    if base is None:
        base = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(base)
        if show_label and title:
            _draw_text_bounded(
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
            fraction = _fraction(hi - tick, 0.0, hi - lo)
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
                tick_text = _format_slope_number(tick, 0)
                _draw_text_bounded(
                    d, (track_x - length - 6 * ss, y), tick_text,
                    font=tick_font, fill=zero_color if is_zero else dim_color,
                    stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                    bounds=(raster_w, raster_h), anchor="rm",
                )
        _STATIC_CACHE[static_key] = base

    img = base.copy()
    d = ImageDraw.Draw(img)
    visual_value = max(lo, min(hi, float(value)))
    marker_fraction = _fraction(hi - visual_value, 0.0, hi - lo)
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
        radius = max(3 * ss, int(round(float(cfg.get("marker_size", 6.0)) * ss)))
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
        _draw_text_bounded(
            d, (value_x, marker_y), value_text,
            font=value_font, fill=text_color, stroke_width=text_stroke,
            stroke_fill=(0, 0, 0, 230), bounds=(raster_w, raster_h), anchor="lm",
        )
    return img


# ---------------------------------------------------------------------------
# Public TeleM entry point
# ---------------------------------------------------------------------------


def _render_bar_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    """Render a TeleM bar indicator.

    Supported configuration keys (all optional):

    Common
    ------
    ``bar_style``: ``"ruler"`` (default), ``"segments"`` or ``"slope"``.
    ``show_value``, ``show_label``, ``show_range_labels``, ``text_color``.

    Ruler
    -----
    ``major_ticks`` / legacy ``ticks``, ``minor_ticks``, ``track_color``,
    ``tick_color``, ``marker_color``, ``marker_size``, ``show_mid_label``,
    ``range_units``, ``title_with_unit``.

    Segments
    --------
    ``segments``, ``segment_gap``, ``segment_radius``, ``gradient`` (list of
    hex colours), ``inactive_color``, ``inactive_alpha``, ``grow_height``,
    ``grow_start``, ``show_min``, ``show_max``.
    """
    if Image is None or ImageDraw is None:
        return None, 0, 0, None

    style = str(cfg.get("bar_style", cfg.get("style", "ruler"))).strip().lower()
    # This lets the same module replace segment_bar later if the dispatcher is
    # unified; normal ``form='bar'`` remains ruler by default.
    if style in {"slope", "grade", "vertical_slope"}:
        img = _render_slope(
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            font_path=font_path,
            value=float(value),
            unit=str(unit or "%"),
            label=str(label or "Slope"),
            cfg=cfg,
            val_min=float(val_min),
            val_max=float(val_max),
            thickness=int(thickness),
            size_px=int(size_px),
            fs=int(fs),
            outline=int(outline),
            ss=max(1, int(ss)),
            formatted_val=formatted_val,
        )
    elif style in {"segment", "segments", "segmented", "segment_bar"}:
        img = _render_segments(
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            font_path=font_path,
            value=float(value),
            unit=str(unit or ""),
            label=str(label or ""),
            cfg=cfg,
            val_min=float(val_min),
            val_max=float(val_max),
            size_px=int(size_px),
            fs=int(fs),
            outline=int(outline),
            ss=max(1, int(ss)),
            formatted_val=formatted_val,
        )
    else:
        img = _render_ruler(
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            font_path=font_path,
            value=float(value),
            unit=str(unit or ""),
            label=str(label or ""),
            cfg=cfg,
            val_min=float(val_min),
            val_max=float(val_max),
            ticks=int(ticks),
            thickness=int(thickness),
            size_px=int(size_px),
            fs=int(fs),
            outline=int(outline),
            ss=max(1, int(ss)),
            formatted_val=formatted_val,
        )

    ss = max(1, int(ss))
    if ss > 1:
        img = img.resize(
            (max(1, int(round(img.width / ss))), max(1, int(round(img.height / ss)))),
            Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS,
        )

    # All annotations are local to the raster.  Returning ``None`` prevents the
    # compositor from drawing the legacy out-of-raster value/range labels a
    # second time.
    return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
