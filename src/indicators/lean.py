"""TeleM ``Przechył`` / Lean indicator — animated rotating graphic.

This is a SEPARATE indicator type from BAR/Ruler.  It is NOT a linear bar: it
rotates a graphic (bike icon or a beam) around its centre according to an
orientation signal (GPMF gyro axis, or optionally FIT grade / terrain incline),
with a sensitivity multiplier and a max-angle clamp.

Motion model (ETAP 12):
    raw_value
      -> normalization (radians->degrees for gyro; 1:1 for grade)
      -> sensitivity multiplier
      -> clamp [-max_angle, +max_angle]
      -> final displayed angle (degrees)

All text (title, tick labels, value readout) is always drawn horizontally —
the widget raster itself is never rotated; only the graphic is rotated around
its centre (pivot = centre of the graphic).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw

from src.indicators.helpers import (
    _BoundedStaticCache,
    _static_cache_key,
    load_font,
    parse_hex_color,
    s,
)

_LEAN_BASE_CACHE = _BoundedStaticCache(max_entries=64)
_LEAN_GRAPHIC_CACHE = _BoundedStaticCache(max_entries=16)
_ROWER_ICO = Path(__file__).resolve().parents[2] / "wzor" / "rower_ico.png"


def _rgb(value: Any, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    c = parse_hex_color(value) if isinstance(value, str) else None
    return c or fallback


def _rgba(value: Any, fallback: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = _rgb(value, fallback)
    return r, g, b, max(0, min(255, int(alpha)))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def lean_angle(raw, cfg: dict[str, Any]) -> float:
    """Raw orientation signal -> final display angle in degrees.

    ``raw`` is in rad/s for GPMF gyro (degrees_per_unit = 180/pi) or in percent
    for FIT grade (degrees_per_unit = 1.0).  ``sensitivity`` scales the signal
    and the result is clamped to ``[-max_angle, +max_angle]``.
    """
    if raw is None:
        return 0.0
    source = str(cfg.get("source", "gyro")).strip().lower()
    if source == "grade":
        degrees_per_unit = 1.0
    else:
        degrees_per_unit = 180.0 / math.pi
    if cfg.get("degrees_per_unit") is not None:
        degrees_per_unit = float(cfg["degrees_per_unit"])
    sensitivity = float(cfg.get("sensitivity", 0.2))
    max_angle = abs(float(cfg.get("max_angle", 15.0)))
    angle = float(raw) * degrees_per_unit * sensitivity
    return _clamp(angle, -max_angle, max_angle)


def _load_lean_graphic(cfg: dict[str, Any], size_px: int) -> Optional[Image.Image]:
    """Load (and cache) the rotatable graphic: bike asset or procedural beam."""
    graphic = str(cfg.get("graphic", "bike")).strip().lower()
    if graphic == "none":
        return None
    marker = _rgba(cfg.get("marker_color", "#FFFFFF"), (255, 255, 255), 255)
    key = (graphic, size_px, marker)
    cached = _LEAN_GRAPHIC_CACHE.get(key)
    if cached is not None:
        return cached

    if graphic == "bike" and _ROWER_ICO.exists():
        try:
            icon = Image.open(_ROWER_ICO).convert("RGBA")
            # Fit into a size_px box preserving aspect ratio.
            scale = size_px / max(1.0, max(icon.width, icon.height))
            new_w = max(1, int(round(icon.width * scale)))
            new_h = max(1, int(round(icon.height * scale)))
            icon = icon.resize((new_w, new_h), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
            _LEAN_GRAPHIC_CACHE[key] = icon
            return icon
        except Exception:
            pass  # fall through to the procedural beam

    # Procedural bike-silhouette beam: two wheels + top tube + pivot dot.
    w = max(24, size_px)
    h = max(12, int(size_px * 0.35))
    img = Image.new("RGBA", (w + 4, h + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = (w + 4) / 2.0
    cy = (h + 4) / 2.0
    r = max(3, int(size_px * 0.12))
    # wheels
    d.ellipse((cx - w / 2.0, cy - r, cx - w / 2.0 + 2 * r, cy + r), fill=marker)
    d.ellipse((cx + w / 2.0 - 2 * r, cy - r, cx + w / 2.0, cy + r), fill=marker)
    # top tube (beam)
    d.rounded_rectangle(
        (cx - w / 2.0 + r + 2, cy - 2, cx + w / 2.0 - r - 2, cy + 2),
        radius=2, fill=marker,
    )
    # centre pivot
    pr = max(2, int(size_px * 0.05))
    d.ellipse((cx - pr, cy - pr, cx + pr, cy + pr), fill=(255, 255, 255, 255))
    _LEAN_GRAPHIC_CACHE[key] = img
    return img


def _render_lean_indicator(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    key: str,
    value: float,
    unit: str,
    label: str,
    cfg: dict[str, Any],
    min_dim: int,
    outline: int,
    fs: int,
    font,
    val_min: float,
    val_max: float,
    ticks: int,
    thickness: int,
    size_px: int,
    ss: int,
    formatted_val: str | None = None,
):
    ss = max(1, int(ss))
    pad = 8 * ss
    g = max(32 * ss, int(size_px * ss))

    show_label = bool(cfg.get("show_label", True))
    show_value = bool(cfg.get("show_value", True))
    show_reference = bool(cfg.get("show_reference", True))
    show_ticks = bool(cfg.get("show_ticks", True))
    uppercase_title = bool(cfg.get("uppercase_title", True))
    decimals = max(0, int(cfg.get("decimals", 0)))
    max_angle = abs(float(cfg.get("max_angle", 15.0)))
    angle = lean_angle(value, cfg)
    missing = value is None

    title_fs = max(8 * ss, int(round(float(cfg.get("title_font_scale", 1.0)) * fs * ss)))
    value_fs = max(8 * ss, int(round(float(cfg.get("value_font_scale", 0.9)) * fs * ss)))
    title_font = load_font(font_path, title_fs)
    value_font = load_font(font_path, value_fs)
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    raw_title = str(cfg.get("title_text", label or "")).strip()
    title = raw_title.upper() if uppercase_title else raw_title
    value_text = f"{angle:+.{decimals}f}\u00b0" if (show_value and not missing) else ""

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    title_h = _text_size(dd, title, title_font, text_stroke)[1] if show_label and title else 0
    value_w = _text_size(dd, value_text, value_font, text_stroke)[0] if value_text else 0
    value_h = _text_size(dd, value_text, value_font, text_stroke)[1] if value_text else 0
    title_gap = 5 * ss if title_h else 0
    value_gap = 4 * ss if value_h else 0

    ref_color = _rgba(cfg.get("track_color", "#FFFFFF"), (255, 255, 255), int(255 * 0.55))
    tick_color = _rgba(cfg.get("tick_color", cfg.get("track_color", "#FFFFFF")),
                       (255, 255, 255), int(255 * 0.35))

    raster_w = max(g + 2 * pad, value_w + 2 * pad, 2 * pad + 40)
    top = pad + title_h + title_gap
    center_y = top + g / 2.0
    raster_h = int(top + g + value_gap + value_h + pad)

    static_key = _static_cache_key(
        "lean_base_v1", font_path, title, title_fs, value_fs, text_stroke,
        show_label, show_reference, show_ticks, max_angle, g, pad,
        raster_w, raster_h, ref_color, tick_color, ss, canvas_w,
    )
    base = _LEAN_BASE_CACHE.get(static_key)
    if base is None:
        base = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(base)
        cx = raster_w / 2.0
        if show_label and title:
            _draw_text_bounded(
                d, (raster_w / 2, pad), title, font=title_font, fill=(255, 255, 255, 255),
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, raster_h), anchor="ma",
            )
        if show_reference:
            d.line((pad, center_y, raster_w - pad, center_y), fill=ref_color,
                   width=max(1, int(round(1.4 * ss))))
        if show_ticks:
            step = 10.0
            tick_range = min(max_angle, 90.0)
            t = -tick_range
            while t <= tick_range + 1e-6:
                frac = _clamp(t / max(1.0, max_angle), -1.0, 1.0)
                x = cx + frac * (g / 2.0 - 4 * ss)
                tl = (4 * ss) if abs(abs(t) - tick_range) < 1e-6 else (3 * ss)
                d.line((x, center_y - tl, x, center_y + tl), fill=tick_color,
                       width=max(1, int(round(1.0 * ss))))
                t += step
        _LEAN_BASE_CACHE[static_key] = base

    img = base.copy()
    d = ImageDraw.Draw(img)

    graphic = _load_lean_graphic(cfg, g)
    if graphic is not None:
        rotated = graphic.rotate(angle, resample=Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC, expand=True)
        img.alpha_composite(rotated, (int(round(raster_w / 2.0 - rotated.width / 2.0)), int(round(center_y - rotated.height / 2.0))))

    if value_text:
        _draw_text_bounded_cached(
            img, (raster_w / 2, top + g + value_gap), value_text,
            font=value_font, font_path=font_path, fill=(255, 255, 255, 255),
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
            bounds=(raster_w, raster_h), anchor="ma",
        )

    return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None


# ── Small text helpers (mirror bar.py so lean.py stays self-contained) ─────

def _text_size(draw: ImageDraw.ImageDraw, text: str, font, stroke: int = 0) -> tuple[int, int, tuple[int, int, int, int]]:
    box = draw.textbbox((0, 0), str(text), font=font, stroke_width=max(0, stroke))
    return max(0, box[2] - box[0]), max(0, box[3] - box[1]), box


def _draw_text_bounded(draw, xy, text, *, font, fill, stroke_width, stroke_fill, bounds, anchor="ma") -> None:
    x, y = float(xy[0]), float(xy[1])
    try:
        box = draw.textbbox((x, y), str(text), font=font, anchor=anchor, stroke_width=stroke_width)
    except TypeError:
        box = draw.textbbox((x, y), str(text), font=font, stroke_width=stroke_width)
        anchor = None
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


_TEXT_TILE_CACHE = _BoundedStaticCache(max_entries=128)


def _draw_text_bounded_cached(target_img, xy, text, *, font, font_path, fill, stroke_width, stroke_fill, bounds, anchor="ma") -> None:
    if not text:
        return
    text_str = str(text)
    f_size = getattr(font, "size", 0)
    tile_key = (text_str, font_path, f_size, fill, stroke_width, stroke_fill, anchor)
    tile_data = _TEXT_TILE_CACHE.get(tile_key)
    if tile_data is None:
        dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dummy)
        try:
            box = dd.textbbox((0, 0), text_str, font=font, anchor=anchor, stroke_width=stroke_width)
        except TypeError:
            box = dd.textbbox((0, 0), text_str, font=font, stroke_width=stroke_width)
        tw = max(1, box[2] - box[0])
        th = max(1, box[3] - box[1])
        tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        try:
            td.text((-box[0], -box[1]), text_str, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, anchor=anchor)
        except TypeError:
            td.text((-box[0], -box[1]), text_str, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        tile_data = (tile, box[0], box[1], box[2], box[3])
        _TEXT_TILE_CACHE[tile_key] = tile_data

    tile, b0, b1, b2, b3 = tile_data
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
    target_img.alpha_composite(tile, (int(round(x + b0 + dx)), int(round(y + b1 + dy))))
