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
    _BoundedStaticCache,
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

_RULER_METRICS_CACHE: dict[tuple, tuple[int, int, int]] = {}
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
    """Draw text clamped inside bounds using a bounded LRU text-tile cache."""
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


def _get_ruler_text_metrics(
    font_path: str,
    title: str,
    title_font,
    show_title: bool,
    range_sample: str,
    range_font,
    show_range: bool,
    value_text: str,
    value_font,
    show_value: bool,
    text_stroke: int,
) -> tuple[int, int, int]:
    key = (
        font_path,
        title if show_title else "",
        range_sample if show_range else "",
        value_text if show_value else "",
        text_stroke,
    )
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


def _render_ruler(
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

    range_sample = f"{_fmt_number(max(abs(val_min), abs(val_max)), decimals)} {unit}".strip()
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
            _draw_text_bounded(
                d, (raster_w / 2, pad_top), title,
                font=title_font, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ma",
            )

        # Track + shadow.
        _line_with_shadow(d, (x1, track_y, x2, track_y), fill=track_color, width=line_w)

        # Ticks all extend upward from the track, matching the reference image.
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
                    _line_with_shadow(
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
            _draw_text_bounded_cached(
                img, (marker_x + value_offset_x, value_y + value_offset_y), value_text,
                font=value_font, font_path=font_path, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ma",
            )

    return img


# ---------------------------------------------------------------------------
# Segmented bar caches and optimized rendering
# ---------------------------------------------------------------------------

_SEG_BASE_CACHE = _BoundedStaticCache(max_entries=64)
_SEG_ACTIVE_CACHE = _BoundedStaticCache(max_entries=128)
_SEG_ICON_CACHE = _BoundedStaticCache(max_entries=16)


def _get_seg_icon(icon_name: str | None, icon_size: int) -> Optional[Image.Image]:
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


# ── ETAP 10T: segment colour-mode helpers ────────────────────────────────

def _parse_thresholds(raw) -> list[dict]:
    """Parse ``segment_thresholds`` from a JSON list or a compact string.

    Accepts: a list of ``{"value": 20, "color": "#ff0000"}`` dicts, a JSON
    string of the same, or a compact ``20:#ff0000;50:#ffaa00;...`` string.
    """
    if isinstance(raw, (list, tuple)):
        return [t for t in raw if isinstance(t, dict)]
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                import json
                data = json.loads(raw)
                if isinstance(data, list):
                    return [t for t in data if isinstance(t, dict)]
            except Exception:
                pass
        out: list[dict] = []
        for part in raw.split(";"):
            part = part.strip()
            if not part or ":" not in part:
                continue
            v, c = part.split(":", 1)
            try:
                out.append({"value": float(v.strip()), "color": c.strip()})
            except (TypeError, ValueError):
                continue
        return out
    return []


def _segment_color_mode(cfg: dict) -> str:
    """``solid`` | ``gradient`` | ``threshold`` (legacy presets default gradient)."""
    mode = str(cfg.get("segment_color_mode", "gradient")).strip().lower()
    if mode not in ("solid", "gradient", "threshold"):
        return "gradient"
    return mode


def _segment_gradient_stops(cfg: dict) -> tuple[str, ...]:
    """Deprecated alias for :func:`_resolve_segment_gradient`."""
    return _resolve_segment_gradient(cfg)


# ── ETAP 10T2: canonical alias resolution (new explicit property wins) ────
# Every legacy key (segments, segment_radius, inactive_color, inactive_alpha,
# gradient) is only an input fallback.  The GUI writes the new keys, and those
# must always take effect even when a v10 preset still carries the legacy key.

def _resolve_segment_count(cfg: dict) -> int:
    """``segment_count`` wins; legacy ``segments`` is the fallback (default 20)."""
    if "segment_count" in cfg:
        try:
            return max(2, int(cfg["segment_count"]))
        except (TypeError, ValueError):
            pass
    try:
        return max(2, int(cfg.get("segments", 20)))
    except (TypeError, ValueError):
        return 20


def _resolve_segment_gradient(cfg: dict) -> tuple[str, ...]:
    """Gradient stops: new ``segment_color_start``/``segment_color_end`` win;
    legacy multi-stop ``gradient`` is only a fallback for untouched presets."""
    has_start = "segment_color_start" in cfg
    has_end = "segment_color_end" in cfg
    if has_start or has_end:
        return (
            str(cfg.get("segment_color_start", "#16A7AF")),
            str(cfg.get("segment_color_end", "#FF9A2E")),
        )
    raw = cfg.get("gradient")
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return tuple(str(c) for c in raw)
    return ("#16A7AF", "#FF9A2E")


def _resolve_segment_inactive_color(cfg: dict) -> str:
    """``segment_inactive_color`` wins; legacy ``inactive_color`` fallback."""
    if "segment_inactive_color" in cfg:
        return str(cfg["segment_inactive_color"])
    return str(cfg.get("inactive_color", "#3E3E3E"))


def _resolve_segment_inactive_opacity(cfg: dict) -> float:
    """Inactive opacity in 0..1.  ``segment_inactive_opacity`` wins; legacy
    ``inactive_alpha`` (0..255) is the fallback (default 95/255)."""
    if "segment_inactive_opacity" in cfg:
        try:
            return max(0.0, min(1.0, float(cfg["segment_inactive_opacity"])))
        except (TypeError, ValueError):
            pass
    if "inactive_alpha" in cfg:
        try:
            return max(0.0, min(1.0, int(cfg["inactive_alpha"]) / 255.0))
        except (TypeError, ValueError):
            pass
    return 95.0 / 255.0


def _resolve_segment_radius(cfg: dict, seg_w: int, seg_h: int, ss: int) -> int:
    """Rounded-rect radius for ``rectangle`` | ``rounded`` | ``pill`` (clamped).

    ``segment_corner_radius`` wins; legacy ``segment_radius`` is the fallback.
    """
    shape = str(cfg.get("segment_shape", "rounded")).strip().lower()
    if shape == "rectangle":
        return 0
    if shape == "pill":
        return max(0, min(seg_w, seg_h) // 2)
    if "segment_corner_radius" in cfg:
        r = float(cfg.get("segment_corner_radius", 1))
    else:
        r = float(cfg.get("segment_radius", 1))
    radius = max(0, int(round(r * ss)))
    return min(radius, max(0, min(seg_w, seg_h) // 2))


def _segment_threshold_color(cfg: dict, v: float) -> tuple[int, int, int]:
    """First threshold whose ``value >= v``; last colour when v exceeds all.

    ``[{"value": 20, "color": "#ff0000"}, ...]`` means 0–20 red, 20–50 next …
    """
    default = _rgb(cfg.get("segment_color", "#16A7AF"), (22, 167, 175))
    thresholds = _parse_thresholds(cfg.get("segment_thresholds"))
    if not thresholds:
        return default
    best = None
    for t in thresholds:
        try:
            tv = float(t.get("value"))
        except (TypeError, ValueError):
            continue
        if v <= tv:
            return _rgb(t.get("color"), default)
        best = t
    if best is not None:
        return _rgb(best.get("color"), default)
    return default


def _segment_seg_color(
    cfg: dict, mode: str, stops: tuple[str, ...],
    seg_index: int, segments: int,
    val_min: float, val_max: float,
    grad_space: str,
) -> tuple[int, int, int]:
    """Colour of one segment, tied to its scale position (never activation order).

    Gradient colours remain attached to the scale position, so ``fill_direction
    = reverse`` never flips the gradient (ETAP 10T §33).
    """
    p = seg_index / max(1, segments - 1) if segments > 1 else 0.0
    if mode == "solid":
        return _rgb(cfg.get("segment_color", "#16A7AF"), (22, 167, 175))
    if mode == "threshold":
        v = val_min + p * (val_max - val_min)
        return _segment_threshold_color(cfg, v)
    # gradient
    if str(grad_space).strip().lower() == "hsv":
        import colorsys as _cs
        def _to_hls(c):
            r, g, b = _rgb(c, (22, 167, 175))
            return _cs.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        hs = [_to_hls(c) for c in stops]
        if len(hs) == 1:
            h, l, s = hs[0]
            r, g, b = _cs.hls_to_rgb(h, l, s)
            return tuple(int(round(x * 255)) for x in (r, g, b))
        scaled = _clamp01(p) * (len(hs) - 1)
        idx = min(len(hs) - 2, int(scaled))
        t = scaled - idx
        a, b = hs[idx], hs[idx + 1]
        h = (a[0] + (b[0] - a[0]) * t) % 1.0
        l = a[1] + (b[1] - a[1]) * t
        s = a[2] + (b[2] - a[2]) * t
        r, g, b = _cs.hls_to_rgb(h, l, s)
        return tuple(int(round(x * 255)) for x in (r, g, b))
    return _gradient_colour(stops, p)


def _resolve_seg_font(cfg: dict, field: str, font_path: str, default_size: int) -> tuple[str, int]:
    """Per-widget font override for value/label/range text.

    ``<field>_font`` = font name/path (None → widget font); ``<field>_font_size``
    = scale multiplier (None → default multiplier already applied by caller).
    """
    font_override = cfg.get(f"{field}_font")
    eff_path = font_path
    if font_override:
        try:
            from src.indicators.helpers import resolve_indicator_font_path
            eff_path = resolve_indicator_font_path(font_override, font_path)
        except Exception:
            eff_path = font_path
    return eff_path, default_size


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
    label_align: str = "center",
    range_align_left: str = "la",
    range_align_right: str = "ra",
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
            bounds=(raster_w, raster_h), anchor=range_align_left,
        )

    if show_max:
        max_txt = _fmt_number(val_max, decimals)
        if range_units and unit:
            max_txt = f"{max_txt} {unit}"
        _draw_text_bounded(
            d, (raster_w - pad_x, bottom_y), max_txt,
            font=range_font, fill=dim_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor=range_align_right,
        )

    # 3. Label and icon
    if show_label and label:
        icon = _get_seg_icon(icon_name, max(10 * ss, int(label_fs * 1.1)))
        if icon and label_align == "center":
            ix = max(0, int((raster_w - icon.width - int(label_font.getlength(str(label)))) / 2) - 3 * ss)
            iy = max(0, int(bottom_y + (bottom_text_h - icon.height) / 2))
            base_img.alpha_composite(icon, (ix, iy))
        if label_align == "center":
            _draw_text_bounded(
                d, (raster_w / 2, bottom_y), str(label).upper() if uppercase_label else str(label),
                font=label_font, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
                bounds=(raster_w, raster_h), anchor="ma",
            )
        elif label_align == "left":
            _draw_text_bounded(
                d, (pad_x, bottom_y), str(label).upper() if uppercase_label else str(label),
                font=label_font, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
                bounds=(raster_w, raster_h), anchor="la",
            )
        else:
            _draw_text_bounded(
                d, (raster_w - pad_x, bottom_y), str(label).upper() if uppercase_label else str(label),
                font=label_font, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
                bounds=(raster_w, raster_h), anchor="ra",
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
    cfg: dict,
    mode: str,
    stops: tuple[str, ...],
    val_min: float,
    val_max: float,
    grad_space: str,
    direction: str,
) -> Optional[Image.Image]:
    if active <= 0:
        return None

    key = (
        "seg_act_v2", active, segments, raster_w, raster_h, ss, pad_x, seg_bottom,
        seg_area_h, gap, radius, round(seg_w, 2), grow_height, round(grow_start, 2),
        mode, stops, val_min, val_max, grad_space, direction,
        _rgb(cfg.get("segment_color", "#16A7AF"), (22, 167, 175)),
        tuple(sorted(
            (float(t.get("value", 0.0)), str(t.get("color", "")))
            for t in _parse_thresholds(cfg.get("segment_thresholds"))
        )),
    )
    layer = _SEG_ACTIVE_CACHE.get(key)
    if layer is not None:
        return layer

    layer = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    reverse = str(direction).strip().lower() == "reverse"
    for a in range(active):
        i = (segments - 1 - a) if reverse else a
        p = i / max(1, segments - 1)
        h_mult = grow_start + (1.0 - grow_start) * p if grow_height else 1.0
        sh = max(2 * ss, int(round(seg_area_h * h_mult)))
        x1 = int(round(pad_x + i * (seg_w + gap)))
        x2 = int(round(pad_x + i * (seg_w + gap) + seg_w - 1))
        y2 = seg_bottom
        y1 = y2 - sh
        colour = _segment_seg_color(cfg, mode, stops, i, segments, val_min, val_max, grad_space)
        fill = (*colour, 255)
        d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill)

    _SEG_ACTIVE_CACHE[key] = layer
    return layer


def _draw_seg_partial_segment(
    img: Image.Image,
    *,
    partial_frac: float,
    segment_index: int,
    segments: int,
    ss: int,
    pad_x: int,
    seg_bottom: int,
    seg_area_h: int,
    gap: int,
    radius: int,
    seg_w: float,
    grow_height: bool,
    grow_start: float,
    colour: tuple[int, int, int],
    direction: str,
) -> None:
    """Fill one segment to ``partial_frac`` width (left→right or right→left)."""
    if partial_frac <= 0.0:
        return
    d = ImageDraw.Draw(img)
    reverse = str(direction).strip().lower() == "reverse"
    i = segment_index
    p = i / max(1, segments - 1)
    h_mult = grow_start + (1.0 - grow_start) * p if grow_height else 1.0
    sh = max(2 * ss, int(round(seg_area_h * h_mult)))
    x1 = int(round(pad_x + i * (seg_w + gap)))
    x2 = int(round(pad_x + i * (seg_w + gap) + seg_w - 1))
    y2 = seg_bottom
    y1 = y2 - sh
    pf = max(0.0, min(1.0, float(partial_frac)))
    if reverse:
        cut = int(round(x1 + (x2 - x1) * (1.0 - pf)))
        fill_x1, fill_x2 = cut, x2
    else:
        cut = int(round(x1 + (x2 - x1) * pf))
        fill_x1, fill_x2 = x1, cut
    if fill_x2 > fill_x1:
        d.rounded_rectangle((fill_x1, y1, fill_x2, y2), radius=radius, fill=(*colour, 255))


def _draw_seg_marker(
    img: Image.Image,
    *,
    marker_x: int,
    cfg: dict,
    ss: int,
    seg_top: int,
    seg_bottom: int,
    marker_zone_top: int,
    marker_zone_bottom: int,
) -> None:
    """Draw the dynamic value marker (none|triangle|line|circle)."""
    style = str(cfg.get("marker_style", "none")).strip().lower()
    if style == "none":
        return
    if not bool(cfg.get("show_marker", True)):
        return

    d = ImageDraw.Draw(img)
    marker_size = max(1, int(round(float(cfg.get("marker_size", 8)) * ss)))
    offset = int(round(float(cfg.get("marker_offset", 0)) * ss))
    marker_color = _rgba(cfg.get("marker_color", "#FFFFFF"), (255, 255, 255), 255)
    border_color = _rgba(cfg.get("marker_border_color", "#000000"), (0, 0, 0), 255)
    border_w = max(0, int(round(float(cfg.get("marker_border_width", 1)) * ss)))
    position = str(cfg.get("marker_position", "top")).strip().lower()

    if position == "bottom":
        base_y = seg_bottom + offset
        if style == "triangle":
            tip = (marker_x, base_y)
            left = (marker_x - marker_size / 2.0, base_y + marker_size)
            right = (marker_x + marker_size / 2.0, base_y + marker_size)
            d.polygon((tip, left, right), fill=marker_color, outline=border_color, width=border_w)
        elif style == "circle":
            r = max(1, marker_size // 2)
            cy = base_y + r
            d.ellipse((marker_x - r, cy - r, marker_x + r, cy + r),
                      fill=marker_color, outline=border_color, width=max(1, border_w))
        else:  # line
            y0 = base_y
            y1 = base_y + marker_size
            d.line((marker_x, y0, marker_x, y1), fill=marker_color, width=max(1, border_w))
    elif position == "center":
        cy = (seg_top + seg_bottom) // 2
        if style == "triangle":
            tip = (marker_x, cy - marker_size / 2.0)
            left = (marker_x - marker_size / 2.0, cy + marker_size / 2.0)
            right = (marker_x + marker_size / 2.0, cy + marker_size / 2.0)
            d.polygon((tip, left, right), fill=marker_color, outline=border_color, width=border_w)
        elif style == "circle":
            r = max(1, marker_size // 2)
            d.ellipse((marker_x - r, cy - r, marker_x + r, cy + r),
                      fill=marker_color, outline=border_color, width=max(1, border_w))
        else:  # line
            d.line((marker_x, seg_top, marker_x, seg_bottom), fill=marker_color,
                   width=max(1, border_w))
    else:  # top
        base_y = seg_top - offset
        if style == "triangle":
            tip = (marker_x, base_y)
            left = (marker_x - marker_size / 2.0, base_y - marker_size)
            right = (marker_x + marker_size / 2.0, base_y - marker_size)
            d.polygon((tip, left, right), fill=marker_color, outline=border_color, width=border_w)
        elif style == "circle":
            r = max(1, marker_size // 2)
            cy = base_y - r
            d.ellipse((marker_x - r, cy - r, marker_x + r, cy + r),
                      fill=marker_color, outline=border_color, width=max(1, border_w))
        else:  # line
            y0 = base_y - marker_size
            y1 = base_y
            d.line((marker_x, y0, marker_x, y1), fill=marker_color, width=max(1, border_w))


def _render_segments(
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
    # NOTE (ETAP 10T): the final composed image is deliberately NOT stored in
    # ``_STATIC_CACHE`` — the old shallow key (segments+icon only) returned stale
    # rasters when config changed (the "segment_radius does nothing" bug).  The
    # static base + active layers below are cached with complete keys; the cheap
    # dynamic parts (active compositing, partial segment, marker, value text)
    # are drawn per frame.

    ss = max(1, int(ss))
    width = max(80 * ss, int(size_px * ss))
    segments = _resolve_segment_count(cfg)
    gap = max(0, int(round(float(cfg.get("segment_gap", 3)) * ss)))
    decimals = max(0, int(cfg.get("decimals", 1)))

    # ── Per-widget fonts (independent control) ──────────────────────────
    value_fs = max(10 * ss, int(round(float(cfg.get("value_font_size", cfg.get("value_font_scale", 1.70))) * fs * ss)))
    label_fs = max(7 * ss, int(round(float(cfg.get("label_font_size", cfg.get("label_font_scale", 0.72))) * fs * ss)))
    range_fs = max(7 * ss, int(round(float(cfg.get("range_font_size", cfg.get("range_font_scale", 0.82))) * fs * ss)))
    value_font_path, value_fs = _resolve_seg_font(cfg, "value", font_path, value_fs)
    label_font_path, label_fs = _resolve_seg_font(cfg, "label", font_path, label_fs)
    range_font_path, range_fs = _resolve_seg_font(cfg, "range", font_path, range_fs)
    value_font = load_font(value_font_path, value_fs)
    label_font = load_font(label_font_path, label_fs)
    range_font = load_font(range_font_path, range_fs)
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    show_value = bool(cfg.get("show_value", True))
    show_label = bool(cfg.get("show_label", True))
    show_min = bool(cfg.get("show_min", True))
    show_max = bool(cfg.get("show_max", True))
    range_units = bool(cfg.get("range_units", False))
    grow_height = bool(cfg.get("grow_height", True))
    grow_start = _clamp01(float(cfg.get("grow_start", 0.55)))
    inactive_alpha = int(round(_resolve_segment_inactive_opacity(cfg) * 255))
    inactive_color = _resolve_segment_inactive_color(cfg)
    inactive = _rgba(inactive_color, (62, 62, 62), inactive_alpha)
    text_color = _rgba(cfg.get("text_color", "#FFFFFF"), (255, 255, 255), 255)
    dim_color = _rgba(cfg.get("range_color", "#E0E0E0"), (224, 224, 224), 255)
    value_color = _rgba(cfg.get("value_color"), text_color[:3], 255) if cfg.get("value_color") else text_color
    label_color = _rgba(cfg.get("label_color"), text_color[:3], 255) if cfg.get("label_color") else text_color
    range_text_color = _rgba(cfg.get("range_color", "#E0E0E0"), dim_color[:3], 255) if "range_color" in cfg else dim_color

    mode = _segment_color_mode(cfg)
    stops = _resolve_segment_gradient(cfg)
    grad_space = str(cfg.get("gradient_space", "rgb")).strip().lower()
    fill_mode = str(cfg.get("segment_fill_mode", "whole")).strip().lower()
    if fill_mode not in ("whole", "partial"):
        fill_mode = "whole"
    direction = str(cfg.get("fill_direction", "forward")).strip().lower()
    if direction not in ("forward", "reverse"):
        direction = "forward"
    value_align = str(cfg.get("value_align", "left")).strip().lower()
    if value_align not in ("left", "center", "right"):
        value_align = "left"
    label_align = str(cfg.get("label_align", "center")).strip().lower()
    if label_align not in ("left", "center", "right"):
        label_align = "center"

    marker_style = str(cfg.get("marker_style", "none")).strip().lower()
    marker_enabled = marker_style != "none"
    marker_position = str(cfg.get("marker_position", "top")).strip().lower()
    marker_size = max(1, int(round(float(cfg.get("marker_size", 8)) * ss)))
    marker_offset = max(0, int(round(float(cfg.get("marker_offset", 0)) * ss)))
    marker_zone_top = 0
    marker_zone_bottom = 0
    if marker_enabled and marker_position == "top":
        marker_zone_top = marker_size + marker_offset
    elif marker_enabled and marker_position == "bottom":
        marker_zone_bottom = marker_size + marker_offset

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
    value_gap = (max(0, int(cfg.get("value_gap", 3))) * ss) if value_h else 0
    label_gap = max(0, int(cfg.get("label_gap", 0))) * ss
    range_gap = max(0, int(cfg.get("range_gap", 0))) * ss
    bottom_text_h = max(label_h, range_h)
    bottom_pad = 3 * ss

    if "segment_height" in cfg and float(cfg.get("segment_height", 0) or 0) > 0:
        seg_area_h = max(8 * ss, int(round(float(cfg["segment_height"]) * ss)))
    else:
        seg_area_h = max(16 * ss, int(round(width * float(cfg.get("segment_height_ratio", 0.105)))))

    raster_w = width + pad_x * 2
    raster_h = int(
        top_pad + value_h + value_gap + marker_zone_top
        + seg_area_h + 5 * ss + marker_zone_bottom
        + bottom_text_h + bottom_pad + label_gap + range_gap
    )
    seg_top = top_pad + value_h + value_gap + marker_zone_top
    seg_bottom = seg_top + seg_area_h
    bottom_y = seg_bottom + 5 * ss + marker_zone_bottom + label_gap

    total_gap = gap * (segments - 1)
    seg_w_override = float(cfg.get("segment_width", 0) or 0) * ss
    if seg_w_override > 0:
        seg_w = seg_w_override
        if seg_w * segments + gap * (segments - 1) > width:
            gap = max(0, int((width - seg_w * segments) // max(1, segments - 1)))
            total_gap = gap * (segments - 1)
    else:
        if total_gap >= width:
            gap = 0
            total_gap = 0
        seg_w = (width - total_gap) / segments
    # ETAP 10T2: a very large segment count can make seg_w < 1 px, which breaks
    # Pillow's rounded_rectangle (x1 > x2).  Fall back to a 1px-wide segment
    # with no gap so segment_count up to 100 renders safely.
    if seg_w < 1.0:
        gap = 0
        total_gap = 0
        seg_w = width / segments
        if seg_w < 1.0:
            seg_w = 1.0

    if value is not None:
        frac = _fraction(float(value), val_min, val_max)
        if fill_mode == "partial" and 0.0 < frac < 1.0:
            scaled = frac * segments
            active = min(segments, int(floor(scaled)))
            partial_frac = max(0.0, min(1.0, scaled - active))
        else:
            active = 0 if frac <= 0.0 else min(segments, int(ceil(frac * segments - 1e-12)))
            partial_frac = 0.0
    else:
        active = 0
        partial_frac = 0.0

    radius = _resolve_segment_radius(cfg, int(round(seg_w)), seg_area_h, ss)

    # 1. Static base layer (inactive segments + labels + range)
    base_key = _static_cache_key(
        "seg_base_v2", font_path, value_font_path, label_font_path, range_font_path,
        raster_w, raster_h, ss, pad_x, top_pad, value_h, value_gap,
        seg_area_h, seg_top, seg_bottom, bottom_y, bottom_text_h, segments, gap, radius,
        round(seg_w, 2), grow_height, round(grow_start, 2), inactive, show_min, show_max, show_label,
        val_min, val_max, decimals, range_units, unit, label, range_fs, label_fs, text_stroke,
        dim_color, text_color, cfg.get("icon"), bool(cfg.get("uppercase_label", True)),
        label_align, marker_zone_top, marker_zone_bottom, label_gap, range_gap
    )
    base_img = _SEG_BASE_CACHE.get(base_key)
    if base_img is None:
        base_img = _build_seg_base_layer(
            raster_w, raster_h, ss, pad_x, top_pad, value_h, value_gap, seg_area_h,
            seg_top, seg_bottom, bottom_y, bottom_text_h, segments, gap, radius, seg_w,
            grow_height, grow_start, inactive, show_min, show_max, show_label, val_min,
            val_max, decimals, range_units, unit, label, range_font_path, range_fs, label_fs,
            text_stroke, range_text_color if "range_color" in cfg else dim_color,
            text_color, cfg.get("icon"), bool(cfg.get("uppercase_label", True)),
            label_align,
        )
        _SEG_BASE_CACHE[base_key] = base_img

    # 2. Active segments + partial + marker + value text on a fresh copy
    out_img = base_img.copy()

    if active > 0:
        active_layer = _get_seg_active_layer(
            active, segments, raster_w, raster_h, ss, pad_x, seg_bottom, seg_area_h,
            gap, radius, seg_w, grow_height, grow_start, cfg, mode, stops,
            val_min, val_max, grad_space, direction,
        )
        if active_layer:
            out_img.alpha_composite(active_layer)
        if partial_frac > 0.0:
            if direction == "reverse":
                part_idx = max(0, segments - active - 1)
            else:
                part_idx = min(segments - 1, active)
            colour = _segment_seg_color(cfg, mode, stops, part_idx, segments, val_min, val_max, grad_space)
            _draw_seg_partial_segment(
                out_img, partial_frac=partial_frac, segment_index=part_idx,
                segments=segments, ss=ss, pad_x=pad_x, seg_bottom=seg_bottom,
                seg_area_h=seg_area_h, gap=gap, radius=radius, seg_w=seg_w,
                grow_height=grow_height, grow_start=grow_start, colour=colour,
                direction=direction,
            )

    # 3. Dynamic marker (never static-cached — position follows current value)
    if value is not None and marker_enabled:
        marker_x = int(round(pad_x + frac * width))
        _draw_seg_marker(
            out_img, marker_x=marker_x, cfg=cfg, ss=ss,
            seg_top=seg_top, seg_bottom=seg_bottom,
            marker_zone_top=marker_zone_top, marker_zone_bottom=marker_zone_bottom,
        )

    # 4. Current value text
    if show_value and value_text:
        d = ImageDraw.Draw(out_img)
        if value_align == "center":
            _draw_text_bounded(
                d, (raster_w / 2, top_pad), value_text,
                font=value_font, fill=value_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
                bounds=(raster_w, raster_h), anchor="ma",
            )
        elif value_align == "right":
            _draw_text_bounded(
                d, (raster_w - pad_x, top_pad), value_text,
                font=value_font, fill=value_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
                bounds=(raster_w, raster_h), anchor="ra",
            )
        else:
            _draw_text_bounded(
                d, (pad_x, top_pad), value_text,
                font=value_font, fill=value_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
                bounds=(raster_w, raster_h), anchor="la",
            )

    return out_img


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
        else ("--%" if missing else f"{_format_slope_number(value, decimals)}%")
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
    value_width = _text_size(dd, value_text, value_font, text_stroke)[0] if show_value else 0

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
            tick_texts = [_format_slope_number(tick, 0) for tick in major_values]
        else:
            tick_texts = []
        tick_widths = [
            _text_size(dd, text, tick_font, text_stroke)[0] for text in tick_texts
        ]
        label_width = max(tick_widths or [0])
        title_width = _text_size(dd, title, title_font, text_stroke)[0] if show_label else 0

        pad_x = 8 * ss
        pad_top = 5 * ss
        title_gap = 5 * ss if show_label and title else 0
        title_h = _text_size(dd, title, title_font, text_stroke)[1] if show_label else 0
        track_x = pad_x + label_width + major_len + 10 * ss
        top = pad_top + title_h + title_gap
        bottom = top + track_height
        value_x = track_x + marker_len + 12 * ss
        raster_w = max(track_x + track_width + pad_x, value_x + value_width + pad_x)
        raster_h = bottom + 6 * ss

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
            value=float(value) if value is not None else None,
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
            value=float(value) if value is not None else None,
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
