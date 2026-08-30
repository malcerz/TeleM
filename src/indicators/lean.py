"""TeleM ``Przechył`` / Lean indicator — animated rotating graphic.

This is a SEPARATE indicator type from BAR/Ruler.  It is NOT a linear bar: it
rotates a graphic (bike icon or a beam) around its centre according to a roll
angle, with mount calibration (offset / invert), a visual sensitivity
multiplier and a max-angle clamp.

Physics (ETAP 13 — no more "rad/s treated as degrees"):
    GPMF ACCL (m/s^2) + GPMF GYRO (rad/s)
        -> complementary filter (src.telemetry_imu) precomputes a DETERMINISTIC
           roll timeline  timestamp -> physical roll [deg]
        -> lean_visual_angle(roll, cfg):
           roll - zero_offset
           * (invert ? -1 : 1)
           * sensitivity            (1° real roll = 1° visual by default)
           clamp [-max_angle, +max_angle]
        -> graphic rotation + optional numeric readout [deg]

FIT grade source is converted with ``degrees(atan(grade/100))`` (terrain
incline angle) and is clearly distinct from bike lean.

All text (title, value readout) is always drawn horizontally — the widget
raster itself is never rotated; only the graphic is rotated around its centre.
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


def clear_lean_caches() -> None:
    """Clear all process-local lean caches between exports/tests."""
    _LEAN_BASE_CACHE.clear()
    _LEAN_GRAPHIC_CACHE.clear()
    cache = globals().get("_TEXT_TILE_CACHE")
    if cache is not None:
        cache.clear()


def _rgb(value: Any, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    c = parse_hex_color(value) if isinstance(value, str) else None
    return c or fallback


def _rgba(value: Any, fallback: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = _rgb(value, fallback)
    return r, g, b, max(0, min(255, int(alpha)))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def lean_visual_angle(roll_deg, cfg: dict[str, Any]) -> float:
    """Physical roll [deg] -> visual angle [deg].

    Pipeline (ETAP 13): roll - zero_offset -> invert -> sensitivity -> clamp.
    Default sensitivity 1.0 means 1° of real roll = 1° of graphic rotation.
    """
    if roll_deg is None:
        return 0.0
    offset = float(cfg.get("zero_offset", 0.0))
    invert = bool(cfg.get("invert_axis", False))
    sensitivity = float(cfg.get("sensitivity", 1.0))
    max_angle = abs(float(cfg.get("max_angle", 30.0)))
    angle = (float(roll_deg) - offset) * (-1.0 if invert else 1.0) * sensitivity
    return _clamp(angle, -max_angle, max_angle)


def lean_angle(raw, cfg: dict[str, Any]) -> float:
    """Interpret the incoming raw value and return the final visual angle [deg].

    - source == "grade": ``raw`` is a grade percent -> physical angle via
      ``degrees(atan(grade/100))``.
    - source == "gyro"/"imu": ``raw`` is the PRECOMPUTED physical roll [deg]
      from the complementary filter (never raw rad/s).

    Then the common visual pipeline: offset -> invert -> sensitivity -> clamp.
    """
    if raw is None:
        return 0.0
    source = str(cfg.get("source", "gyro")).strip().lower()
    if source == "grade":
        from src.telemetry_imu import grade_to_angle_deg
        roll_deg = grade_to_angle_deg(raw)
    else:
        roll_deg = float(raw)
    return lean_visual_angle(roll_deg, cfg)


class _LeanRotationSource:
    __slots__ = (
        "graphic",
        "padded_graphic",
        "gw",
        "gh",
        "pivot_px",
        "pivot_py",
        "pad_ref",
        "gx_ref",
        "gy_ref",
        "Cx",
        "Cy",
        "Px",
        "Py",
        "corners_src_rel",
    )

    def __init__(
        self,
        graphic: Image.Image,
        padded_graphic: Image.Image,
        gw: int,
        gh: int,
        pivot_px: float,
        pivot_py: float,
        pad_ref: int,
        gx_ref: int,
        gy_ref: int,
        Cx: float,
        Cy: float,
        Px: float,
        Py: float,
        corners_src_rel: tuple[tuple[float, float], ...],
    ):
        self.graphic = graphic
        self.padded_graphic = padded_graphic
        self.gw = gw
        self.gh = gh
        self.pivot_px = pivot_px
        self.pivot_py = pivot_py
        self.pad_ref = pad_ref
        self.gx_ref = gx_ref
        self.gy_ref = gy_ref
        self.Cx = Cx
        self.Cy = Cy
        self.Px = Px
        self.Py = Py
        self.corners_src_rel = corners_src_rel


def _load_lean_graphic(cfg: dict[str, Any], size_px: int) -> Optional[Image.Image]:
    """Load (and cache) the rotatable graphic: bike asset or procedural beam."""
    src = _load_lean_rotation_source(cfg, size_px)
    return src.graphic if src is not None else None


def _load_lean_rotation_source(cfg: dict[str, Any], size_px: int) -> Optional[_LeanRotationSource]:
    """Load (and cache) the rotation source image, padded raster and geometric metadata."""
    graphic_name = str(cfg.get("graphic", "bike")).strip().lower()
    if graphic_name == "none":
        return None
    marker = _rgba(cfg.get("marker_color", "#FFFFFF"), (255, 255, 255), 255)
    pivot_x_cfg = _clamp(float(cfg.get("pivot_x", 0.5)), 0.0, 1.0)
    pivot_y_cfg = _clamp(float(cfg.get("pivot_y", 1.0)), 0.0, 1.0)
    key = (graphic_name, size_px, marker, pivot_x_cfg, pivot_y_cfg)
    cached = _LEAN_GRAPHIC_CACHE.get(key)
    if cached is not None:
        return cached

    icon_img: Optional[Image.Image] = None
    if graphic_name == "bike" and _ROWER_ICO.exists():
        try:
            icon = Image.open(_ROWER_ICO).convert("RGBA")
            scale = size_px / max(1.0, max(icon.width, icon.height))
            new_w = max(1, int(round(icon.width * scale)))
            new_h = max(1, int(round(icon.height * scale)))
            icon_img = icon.resize(
                (new_w, new_h),
                Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS,
            )
        except Exception:
            icon_img = None

    if icon_img is None:
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
        icon_img = img

    gw, gh = icon_img.size
    pivot_px = pivot_x_cfg * gw
    pivot_py = pivot_y_cfg * gh
    pad_ref = 2 * max(gw, gh) + 4
    gx_ref = int(round(pad_ref / 2.0 - pivot_px))
    gy_ref = int(round(pad_ref / 2.0 - pivot_py))
    Cx = pad_ref / 2.0
    Cy = pad_ref / 2.0

    pad_margin = 4
    padded_graphic = Image.new("RGBA", (gw + 2 * pad_margin, gh + 2 * pad_margin), (0, 0, 0, 0))
    padded_graphic.alpha_composite(icon_img, (pad_margin, pad_margin))
    Px = (Cx - gx_ref) + pad_margin
    Py = (Cy - gy_ref) + pad_margin

    corners_src_rel = (
        (gx_ref - Cx, gy_ref - Cy),
        (gx_ref + gw - Cx, gy_ref - Cy),
        (gx_ref + gw - Cx, gy_ref + gh - Cy),
        (gx_ref - Cx, gy_ref + gh - Cy),
    )

    source_obj = _LeanRotationSource(
        graphic=icon_img,
        padded_graphic=padded_graphic,
        gw=gw,
        gh=gh,
        pivot_px=pivot_px,
        pivot_py=pivot_py,
        pad_ref=pad_ref,
        gx_ref=gx_ref,
        gy_ref=gy_ref,
        Cx=Cx,
        Cy=Cy,
        Px=Px,
        Py=Py,
        corners_src_rel=corners_src_rel,
    )
    _LEAN_GRAPHIC_CACHE[key] = source_obj
    return source_obj


def _graphic_pivot(cfg: dict[str, Any], gw: int, gh: int) -> tuple[float, float]:
    """Pivot point in graphic pixels from normalized config values (0..1).

    ``pivot_x`` / ``pivot_y`` default to 0.5 / 1.0 (bottom-centre — the natural
    "planted at the ground" point for a bike graphic).  Old configs without the
    fields get these defaults (backward compatible).
    """
    pivot_x = _clamp(float(cfg.get("pivot_x", 0.5)), 0.0, 1.0)
    pivot_y = _clamp(float(cfg.get("pivot_y", 1.0)), 0.0, 1.0)
    return pivot_x * gw, pivot_y * gh


def _rotate_paste_params(
    gw: int, gh: int, pivot_px: float, pivot_py: float,
    raster_w: int, center_y: float,
) -> tuple[int, float, float, float, float]:
    """Pad-rotate around the pivot.

    Returns ``(pad, paste_x, paste_y, screen_pivot_x, screen_pivot_y)``.

    The graphic is composited onto a square pad with its pivot at the pad
    CENTRE, the pad is rotated in place (so the pivot point never moves), and
    the pad is pasted so the pivot lands where it sat when the graphic was
    centred in the widget.  This keeps the pivot at the same screen position
    for every angle — the bike looks "planted" at its pivot instead of
    rotating around the image centre.
    """
    pad = 2 * max(gw, gh) + 4
    screen_pivot_x = raster_w / 2.0 + (pivot_px - gw / 2.0)
    screen_pivot_y = center_y + (pivot_py - gh / 2.0)
    return pad, screen_pivot_x - pad / 2.0, screen_pivot_y - pad / 2.0, screen_pivot_x, screen_pivot_y


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
    max_angle = abs(float(cfg.get("max_angle", 30.0)))
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

    skip_dynamic_graphic = bool(cfg.get("_skip_dynamic_graphic", False))
    rot_src = _load_lean_rotation_source(cfg, g)
    if rot_src is not None and not skip_dynamic_graphic:
        pad_ref, paste_x_ref, paste_y_ref, _sx, _sy = _rotate_paste_params(
            rot_src.gw, rot_src.gh, rot_src.pivot_px, rot_src.pivot_py, raster_w, center_y
        )
        px_ref = int(round(paste_x_ref))
        py_ref = int(round(paste_y_ref))

        if abs(angle) < 1e-6:
            dest_x = px_ref + rot_src.gx_ref
            dest_y = py_ref + rot_src.gy_ref
            cx0 = max(0, dest_x)
            cy0 = max(0, dest_y)
            cx1 = min(raster_w, dest_x + rot_src.gw)
            cy1 = min(raster_h, dest_y + rot_src.gh)
            if cx1 > cx0 and cy1 > cy0:
                if (cx0, cy0, cx1, cy1) == (dest_x, dest_y, dest_x + rot_src.gw, dest_y + rot_src.gh):
                    img.alpha_composite(rot_src.graphic, (dest_x, dest_y))
                else:
                    cropped = rot_src.graphic.crop((cx0 - dest_x, cy0 - dest_y, cx1 - dest_x, cy1 - dest_y))
                    img.alpha_composite(cropped, (cx0, cy0))
        else:
            rad = -math.radians(angle)
            a_mat = round(math.cos(rad), 15)
            b_mat = round(math.sin(rad), 15)
            d_mat = round(-math.sin(rad), 15)
            e_mat = round(math.cos(rad), 15)

            rot_c = [
                (a_mat * u + d_mat * v + rot_src.Cx, b_mat * u + e_mat * v + rot_src.Cy)
                for u, v in rot_src.corners_src_rel
            ]
            min_xd = min(c[0] for c in rot_c)
            max_xd = max(c[0] for c in rot_c)
            min_yd = min(c[1] for c in rot_c)
            max_yd = max(c[1] for c in rot_c)

            margin = 4
            xd0 = max(0, int(math.floor(min_xd)) - margin)
            yd0 = max(0, int(math.floor(min_yd)) - margin)
            xd1 = min(rot_src.pad_ref, int(math.ceil(max_xd)) + margin)
            yd1 = min(rot_src.pad_ref, int(math.ceil(max_yd)) + margin)

            tw = xd1 - xd0
            th = yd1 - yd0

            c_x = a_mat * (xd0 - rot_src.Cx) + b_mat * (yd0 - rot_src.Cy) + rot_src.Px
            c_y = d_mat * (xd0 - rot_src.Cx) + e_mat * (yd0 - rot_src.Cy) + rot_src.Py
            matrix = (a_mat, b_mat, c_x, d_mat, e_mat, c_y)

            tight_rot = rot_src.padded_graphic.transform(
                (tw, th),
                Image.Transform.AFFINE,
                matrix,
                resample=Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC,
            )

            dest_x = px_ref + xd0
            dest_y = py_ref + yd0
            cx0 = max(0, dest_x)
            cy0 = max(0, dest_y)
            cx1 = min(raster_w, dest_x + tw)
            cy1 = min(raster_h, dest_y + th)
            if cx1 > cx0 and cy1 > cy0:
                if (cx0, cy0, cx1, cy1) == (dest_x, dest_y, dest_x + tw, dest_y + th):
                    img.alpha_composite(tight_rot, (dest_x, dest_y))
                else:
                    cropped = tight_rot.crop((cx0 - dest_x, cy0 - dest_y, cx1 - dest_x, cy1 - dest_y))
                    img.alpha_composite(cropped, (cx0, cy0))

    if value_text:
        _draw_text_bounded_cached(
            img, (raster_w / 2, top + g + value_gap), value_text,
            font=value_font, font_path=font_path, fill=(255, 255, 255, 255),
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
            bounds=(raster_w, raster_h), anchor="ma",
        )

    return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None


def get_lean_gpu_transform_info(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    key: str,
    value: float | None,
    cfg: dict[str, Any],
    font_path: str = "",
    label: str = "",
    min_dim: int = 1080,
    fs: int = 24,
    outline: int = 2,
    thickness: int = 4,
    size_px: int = 120,
    ss: int = 1,
) -> tuple[float, Image.Image, float, float, float, float, int, int, int, int] | None:
    """Computes lean indicator transform parameters for native D3D11 GPU rendering.

    Returns:
        (angle, sprite_graphic, pivot_px, pivot_py, screen_pivot_x, screen_pivot_y, dst_x, dst_y, tight_w, tight_h)
        or None if no graphic is configured.
    """
    ss = max(1, int(ss))
    pad = 8 * ss
    g = max(32 * ss, int(size_px * ss))

    show_label = bool(cfg.get("show_label", True))
    show_value = bool(cfg.get("show_value", True))
    uppercase_title = bool(cfg.get("uppercase_title", True))
    decimals = max(0, int(cfg.get("decimals", 0)))
    angle = lean_angle(value, cfg)
    missing = value is None

    title_fs = max(8 * ss, int(round(float(cfg.get("title_font_scale", 1.0)) * fs * ss)))
    value_fs = max(8 * ss, int(round(float(cfg.get("value_font_scale", 0.9)) * fs * ss)))
    if not font_path:
        font_path = layout.get("font_path", "arial.ttf") if isinstance(layout, dict) else "arial.ttf"
    title_font = load_font(font_path, title_fs) if font_path else None
    value_font = load_font(font_path, value_fs) if font_path else None
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    raw_title = str(cfg.get("title_text", label or "")).strip()
    title = raw_title.upper() if uppercase_title else raw_title
    value_text = f"{angle:+.{decimals}f}\u00b0" if (show_value and not missing) else ""

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    title_h = _text_size(dd, title, title_font, text_stroke)[1] if show_label and title and title_font else 0
    value_w = _text_size(dd, value_text, value_font, text_stroke)[0] if value_text and value_font else 0
    value_h = _text_size(dd, value_text, value_font, text_stroke)[1] if value_text and value_font else 0
    title_gap = 5 * ss if title_h else 0
    value_gap = 4 * ss if value_h else 0

    raster_w = max(g + 2 * pad, value_w + 2 * pad, 2 * pad + 40)
    top = pad + title_h + title_gap
    center_y = top + g / 2.0
    raster_h = int(top + g + value_gap + value_h + pad)

    rot_src = _load_lean_rotation_source(cfg, g)
    if rot_src is None:
        return None

    pad_ref, paste_x_ref, paste_y_ref, _sx, _sy = _rotate_paste_params(
        rot_src.gw, rot_src.gh, rot_src.pivot_px, rot_src.pivot_py, raster_w, center_y
    )
    px_ref = int(round(paste_x_ref))
    py_ref = int(round(paste_y_ref))

    screen_x = s(cfg["x"], canvas_w) - raster_w // 2
    screen_y = s(cfg["y"], canvas_h) - raster_h // 2
    screen_pivot_x = float(screen_x + _sx)
    screen_pivot_y = float(screen_y + _sy)

    rad = -math.radians(angle)
    a_mat = round(math.cos(rad), 15)
    b_mat = round(math.sin(rad), 15)
    d_mat = round(-math.sin(rad), 15)
    e_mat = round(math.cos(rad), 15)

    rot_c = [
        (a_mat * u + d_mat * v + rot_src.Cx, b_mat * u + e_mat * v + rot_src.Cy)
        for u, v in rot_src.corners_src_rel
    ]
    min_xd = min(c[0] for c in rot_c)
    max_xd = max(c[0] for c in rot_c)
    min_yd = min(c[1] for c in rot_c)
    max_yd = max(c[1] for c in rot_c)

    margin = 4
    xd0 = max(0, int(math.floor(min_xd)) - margin)
    yd0 = max(0, int(math.floor(min_yd)) - margin)
    xd1 = min(rot_src.pad_ref, int(math.ceil(max_xd)) + margin)
    yd1 = min(rot_src.pad_ref, int(math.ceil(max_yd)) + margin)

    tw = xd1 - xd0
    th = yd1 - yd0
    dst_x = screen_x + px_ref + xd0
    dst_y = screen_y + py_ref + yd0

    return (
        float(angle),
        rot_src.graphic,
        float(rot_src.pivot_px),
        float(rot_src.pivot_py),
        screen_pivot_x,
        screen_pivot_y,
        int(dst_x),
        int(dst_y),
        int(tw),
        int(th),
    )


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
