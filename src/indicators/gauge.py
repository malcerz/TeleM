"""Gauge-form indicator rendering — tick marks, numbers, shadow, needle, centre text.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import math

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import (
    _STATIC_CACHE,
    _static_cache_key,
    compose_5q_optimized,
    load_font,
    parse_hex_color,
    s,
)
# ── ETAP 2C: renderer-reported dynamic-support info for AUTO regions ──────────
# Keyed by indicator key. Updated by EVERY _render_gauge_indicator call so the
# AMD native exporter can derive ghost-free AUTO upload rectangles from the
# exact geometry the renderer just painted (needle band, value-text box) plus
# a style/geometry signature used as the texture epoch key. Purely
# informational — recording NEVER affects rendered pixels.
GAUGE_DYNAMIC_INFO: dict = {}


def record_gauge_dynamic_info(key, *, kind, supported, rotation=0,
                              widget_size=None, needle_bbox=None,
                              text_bbox=None, sig=None):
    """Store the latest render's dynamic-support geometry for ``key``."""
    GAUGE_DYNAMIC_INFO[key] = {
        "kind": kind,
        "supported": bool(supported),
        "rotation": int(rotation) % 360,
        "widget_size": widget_size,
        "needle_bbox": needle_bbox,
        "text_bbox": text_bbox,
        "sig": sig,
    }


def get_gauge_dynamic_info(key):
    """Return the latest dynamic-support record for ``key`` (or None)."""
    return GAUGE_DYNAMIC_INFO.get(key)


def _gauge_ticks(display_min: float, raw_max: float, ticks: int) -> tuple:
    """Compute gauge scale parameters from the requested min/max.

    Returns ``(display_min, display_max, step_val, major_intervals,
    sub_ticks_count, total_ticks)``. ``display_max`` is rounded UP to the next
    multiple of a "nice" step so that major tick labels land on round numbers
    (e.g. requested max 180 -> display 0..200 with labels 0/50/100/150/200).
    """
    if raw_max > 0:
        display_max = float(math.ceil(raw_max / 10.0) * 10)
    else:
        display_max = 100.0
    if display_max <= display_min:
        display_max = display_min + 10.0

    span = display_max - display_min

    if span <= 15:
        step_val = 1.0 if span <= 5 else 5.0
    elif span <= 60:
        step_val = 10.0
    elif span <= 140:
        step_val = 20.0
    elif span <= 300:
        step_val = 50.0
    else:
        step_val = 100.0

    # Round the displayed maximum UP to the next multiple of step_val, so the
    # major tick labels land on round numbers (e.g. max 180 -> 0,50,...,200).
    major_intervals = max(1, int(math.ceil(span / step_val)))
    display_max = display_min + major_intervals * step_val
    span = display_max - display_min

    sub_ticks_count = max(1, ticks) if ticks > 0 else 10
    total_ticks = major_intervals * sub_ticks_count
    return (display_min, display_max, step_val, major_intervals,
            sub_ticks_count, total_ticks)


def _render_compass_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    """Render a lightweight fixed-dial GPS course compass.

    ``value`` is already the canonical telemetry ``heading``.  This function
    deliberately contains no GPS/source/bearing logic; it only maps the
    absolute degree value to screen geometry.
    """
    del layout, key, unit, label, val_min, val_max, ticks, font
    ss = max(1, int(ss))
    radius = max(20, int(round(size_px * ss)))
    img_size = max(48, int(round(size_px * 2.4 * ss)))
    cx = cy = img_size // 2
    ring_r = max(12, int(round(radius * 0.88)))

    ring_rgb = parse_hex_color(cfg.get("compass_ring_color", "#B8C7D9")) or (184, 199, 217)
    tick_rgb = parse_hex_color(cfg.get("compass_tick_color", "#DDE7F2")) or (221, 231, 242)
    cardinal_rgb = parse_hex_color(cfg.get("compass_cardinal_color", "#FFFFFF")) or (255, 255, 255)
    needle_rgb = parse_hex_color(cfg.get("compass_needle_color", cfg.get("needle_color", "#FFD42A"))) or (255, 212, 42)
    heading_rgb = parse_hex_color(cfg.get("compass_heading_color", cfg.get("text_color", "#FFFFFF"))) or (255, 255, 255)
    ring_width = max(1, int(round(float(cfg.get("compass_ring_width", 1.5)) * ss)))
    tick_width = max(1, int(round(float(cfg.get("compass_tick_width", 1.0)) * ss)))
    major_width = max(tick_width, int(round(tick_width * 1.6)))
    tick_degrees = max(1, int(cfg.get("compass_tick_degrees", 15)))
    major_degrees = max(tick_degrees, int(cfg.get("compass_major_tick_degrees", 45)))
    pixel_profile = str(cfg.get("tick_profile", "default")).strip().lower() == "pixel"
    major_len = max(4, int(round(radius * (0.14 if pixel_profile else 0.10))))
    minor_len = max(2, int(round(radius * (0.065 if pixel_profile else 0.055))))

    def screen_angle(degrees: float) -> float:
        # PIL's 0° points east; geographic 0° must point up.
        return math.radians(float(degrees) - 90.0)

    static_key = _static_cache_key(
        "compass_static_v1", img_size, radius, ring_r, font_path, fs, outline,
        ring_rgb, tick_rgb, cardinal_rgb, ring_width, tick_width, major_width,
        tick_degrees, major_degrees, pixel_profile,
        bool(cfg.get("compass_show_cardinals", True)),
    )
    img = _STATIC_CACHE.get(static_key)
    if img is None:
        img = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse(
            (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
            outline=(*ring_rgb, 235), width=ring_width,
        )
        for degrees in range(0, 360, tick_degrees):
            angle = screen_angle(degrees)
            major = degrees % major_degrees == 0
            length = major_len if major else minor_len
            outer = ring_r - ring_width
            inner = outer - length
            x1 = cx + math.cos(angle) * inner
            y1 = cy + math.sin(angle) * inner
            x2 = cx + math.cos(angle) * outer
            y2 = cy + math.sin(angle) * outer
            if pixel_profile:
                width = max(1, int(round((tick_width * (1.35 if major else 0.75)))))
                draw.line((round(x1), round(y1), round(x2), round(y2)),
                          fill=(*tick_rgb, 245), width=width)
            else:
                draw.line((x1, y1, x2, y2), fill=(*tick_rgb, 245), width=major_width if major else tick_width)

        compass_font = load_font(font_path, max(8, int(round(fs * ss))))
        if cfg.get("compass_show_cardinals", True):
            label_radius = ring_r - int(round(radius * 0.22))
            for degrees, text in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
                angle = screen_angle(degrees)
                tx = cx + math.cos(angle) * label_radius
                ty = cy + math.sin(angle) * label_radius
                draw.text((tx, ty), text, font=compass_font, anchor="mm",
                          fill=(*cardinal_rgb, 255), stroke_width=max(1, outline * ss // 2),
                          stroke_fill=(0, 0, 0, 230))
        _STATIC_CACHE[static_key] = img

    img = img.copy()
    draw = ImageDraw.Draw(img)

    missing = bool(cfg.get("_compass_missing", False)) or value is None
    heading = None
    if not missing:
        try:
            heading = float(value) % 360.0
            if not math.isfinite(heading):
                heading = None
        except (TypeError, ValueError):
            heading = None

    if heading is not None:
        angle = screen_angle(heading)
        needle_tip = int(round(ring_r * float(cfg.get("compass_needle_length", 0.62))))
        needle_base = max(2, int(round(ring_r * 0.08)))
        px = -math.sin(angle)
        py = math.cos(angle)
        tip_x = cx + math.cos(angle) * needle_tip
        tip_y = cy + math.sin(angle) * needle_tip
        base_x = cx + math.cos(angle) * needle_base
        base_y = cy + math.sin(angle) * needle_base
        half_width = max(2, int(round(float(cfg.get("compass_needle_width", 3.0)) * ss)))
        draw.polygon([
            (base_x + px * half_width, base_y + py * half_width),
            (base_x - px * half_width, base_y - py * half_width),
            (tip_x, tip_y),
        ], fill=(*needle_rgb, 255))
        marker_radius = max(2, int(round(float(cfg.get("compass_marker_size", 4.0)) * ss)))
        draw.ellipse((cx - marker_radius, cy - marker_radius,
                      cx + marker_radius, cy + marker_radius),
                     fill=(*needle_rgb, 255), outline=(*ring_rgb, 255),
                     width=max(1, ss))

    if cfg.get("compass_show_heading", cfg.get("show_value", True)):
        heading_text = formatted_val if formatted_val is not None else ("--°" if heading is None else f"{int(round(heading)) % 360:03d}°")
        heading_font = load_font(font_path, max(8, int(round(fs * 0.78 * ss))))
        draw.text((cx, cy + int(round(radius * 0.34))), heading_text,
                  font=heading_font, anchor="mm", fill=(*heading_rgb, 255),
                  stroke_width=max(1, outline * ss // 2), stroke_fill=(0, 0, 0, 230))

    if ss > 1:
        img = img.resize((max(1, int(round(img_size / ss))), max(1, int(round(img_size / ss)))), Image.LANCZOS)
    opacity = max(0.0, min(1.0, float(cfg.get("opacity", 1.0))))
    if opacity < 1.0:
        alpha = img.getchannel("A").point(lambda a: int(round(a * opacity)))
        img.putalpha(alpha)
    return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None


def _render_gauge_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    """Render a gauge-form indicator (background cached)."""
    if cfg.get("gauge_style") == "compass" or cfg.get("gauge_mode") == "compass":
        # ETAP 2C: a compass dial is fully dynamic (rotating ring, heading
        # text) — no stable static/dynamic pixel split exists, so AUTO region
        # derivation reports "unsupported" and the exporter falls back to
        # full-tile GPU uploads for such widgets.
        record_gauge_dynamic_info(
            key, kind="compass", supported=False,
            rotation=int(cfg.get("rotation", 0)) % 360)
        return _render_compass_indicator(
            canvas_w, canvas_h, layout, font_path, key, value, unit, label,
            cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness,
            size_px, ss, formatted_val=formatted_val,
        )
    ss = max(1, ss)
    gauge_fs = max(8, fs * ss)
    gauge_font = load_font(font_path, gauge_fs)
    gauge_outline = outline * ss
    radius = size_px * ss
    img_size = int(radius * 2.4)
    out_gauge_size = int(size_px * 2.4)
    cx = cy = img_size // 2
    start_deg = int(cfg.get("start_angle", 180))
    sweep_deg = int(cfg.get("sweep_angle", 180))
    end_deg = start_deg + sweep_deg

    min_val_cfg = cfg.get("min_val")
    max_val_cfg = cfg.get("max_val")

    if min_val_cfg is not None:
        display_min = float(math.floor(float(min_val_cfg) / 10.0) * 10)
    else:
        display_min = 0.0

    if max_val_cfg is not None:
        raw_max = float(max_val_cfg)
    elif val_max > 0:
        raw_max = val_max
    else:
        raw_max = 100.0

    (display_min, display_max, step_val, major_intervals,
     sub_ticks_count, total_ticks) = _gauge_ticks(display_min, raw_max, ticks)
    pixel_profile = str(cfg.get("tick_profile", "default")).strip().lower() == "pixel"

    # ── Static background: tick marks + numbers (cached) ──
    bg_key = _static_cache_key(
        "gauge_bg", img_size, start_deg, sweep_deg,
        display_min, display_max, ticks, thickness, ss, gauge_fs, font_path, outline,
        pixel_profile,
    )
    bg = _STATIC_CACHE.get(bg_key)
    if bg is None:
        bg = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(bg)

        for i in range(total_ticks + 1):
            a = math.radians(start_deg + (end_deg - start_deg) * i / total_ticks)
            cos_a, sin_a = math.cos(a), math.sin(a)
            if i % sub_ticks_count == 0:
                # Główna kreska (pełna dziesiątka) — grubsza i dłuższa z etykietą
                if pixel_profile:
                    tick_len = max(8 * ss, radius * 0.12)
                    tick_width = max(3 * ss, int(round(thickness * 1.15 * ss)))
                else:
                    tick_len = thickness * 1.4 * ss
                    tick_width = max(3 * ss, int(thickness * 0.8) * ss)
                tick_val = display_min + (display_max - display_min) * (i / total_ticks)
                txt_tick = f"{tick_val:.0f}"
                text_radius = radius - tick_len - (radius * 0.16)
                tx, ty = cx + cos_a * text_radius, cy + sin_a * text_radius
                draw.text((tx, ty), txt_tick, font=gauge_font,
                    fill=(255, 255, 255, 240), stroke_width=ss,
                    stroke_fill=(0, 0, 0, 255), anchor="mm")
            elif sub_ticks_count % 2 == 0 and i % (sub_ticks_count // 2) == 0:
                # Średnia kreska pośrodku (np. 5)
                if pixel_profile:
                    tick_len = max(5 * ss, radius * 0.075)
                    tick_width = max(2 * ss, int(round(thickness * 0.70 * ss)))
                else:
                    tick_len = thickness * 0.9 * ss
                    tick_width = max(2 * ss, int(thickness * 0.5) * ss)
            else:
                # Mniejsza i cieńsza kreska (sub-tick)
                if pixel_profile:
                    tick_len = max(3 * ss, radius * 0.035)
                    tick_width = max(1 * ss, int(round(thickness * 0.42 * ss)))
                else:
                    tick_len = thickness * 0.5 * ss
                    tick_width = max(1 * ss, int(thickness * 0.3) * ss)
            r_out, r_in = radius, radius - tick_len
            x1, y1 = cx + cos_a * r_in, cy + sin_a * r_in
            x2, y2 = cx + cos_a * r_out, cy + sin_a * r_out
            pdx, pdy = -sin_a, cos_a
            hw = tick_width / 2
            draw.polygon([
                (x1 + pdx * hw, y1 + pdy * hw),
                (x1 - pdx * hw, y1 - pdy * hw),
                (x2 - pdx * hw, y2 - pdy * hw),
                (x2 + pdx * hw, y2 + pdy * hw),
            ], fill=(240, 240, 240, 255))

        # Static shadow
        shadow_offset = max(2 * ss, int(radius * 0.025))
        alpha = bg.split()[3].point(lambda x: int(x * 0.35))
        shadow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        shadow.paste(bg, (shadow_offset, shadow_offset))
        shadow.putalpha(alpha)
        bg = Image.alpha_composite(shadow, bg)
        if ss > 1:
            bg = bg.resize((out_gauge_size, out_gauge_size), Image.LANCZOS)
        _STATIC_CACHE[bg_key] = bg

    # ── Dynamic elements: needle + center text ──
    img = bg.copy()
    draw = ImageDraw.Draw(img)

    draw_needle = False
    if value is not None:
        try:
            val_num = float(value)
            frac = max(0.0, min(1.0, (val_num - display_min) / (display_max - display_min))) if display_max > display_min else 0.0
            draw_needle = True
        except (TypeError, ValueError):
            frac = 0.0
    else:
        frac = 0.0

    ang = math.radians(start_deg + (end_deg - start_deg) * frac)

    # Needle
    needle_len_rel = cfg.get("needle_length", 1.1)
    # The background is rendered at `radius * ss` and downscaled to output
    # space, while the needle is drawn in output space — so scale by /ss.
    needle_r_out = max(2, int(radius * needle_len_rel / ss))
    needle_r_in = max(1, int(radius * 0.05))
    needle_width_px = max(2, int(cfg.get("needle_width", 4) * (1.8 if pixel_profile else 1.5)))
    needle_rgb = parse_hex_color(cfg.get("needle_color", "#DC3232")) or (220, 50, 50)
    needle_fill = (needle_rgb[0], needle_rgb[1], needle_rgb[2], 255)

    # For cached bg we downscaled, so coordinates are in output space
    _cx, _cy = out_gauge_size // 2, out_gauge_size // 2
    pdx, pdy = -math.sin(ang), math.cos(ang)
    tip_x = _cx + math.cos(ang) * needle_r_out
    tip_y = _cy + math.sin(ang) * needle_r_out
    base_x = _cx + math.cos(ang) * needle_r_in
    base_y = _cy + math.sin(ang) * needle_r_in

    if draw_needle:
        draw.polygon([
            (base_x + pdx * needle_width_px / 2, base_y + pdy * needle_width_px / 2),
            (base_x - pdx * needle_width_px / 2, base_y - pdy * needle_width_px / 2),
            (tip_x, tip_y),
        ], fill=needle_fill)

    # Marker (center dot cap)
    show_marker = bool(cfg.get("show_marker", False))
    marker_size = int(cfg.get("marker_size", 0))
    if show_marker and marker_size > 0:
        r = max(1, marker_size)
        marker_color = parse_hex_color(cfg.get("marker_color", "#333333")) or (51, 51, 51)
        marker_fill = (marker_color[0], marker_color[1], marker_color[2], 255)
        draw.ellipse([
            _cx - r, _cy - r,
            _cx + r, _cy + r
        ], fill=marker_fill, outline=(120, 120, 120, 255), width=1)

    # Center text — always the current value, honouring show_value/show_units
    # (formatted_val is built by the compositor from those flags).
    show_value = cfg.get("show_value", True)
    _fs_ds = max(8, fs)
    _c_font = load_font(font_path, _fs_ds)
    _text_support = None  # ETAP 2C: dynamic value-text support bbox
    if show_value:
        txt_main = formatted_val if formatted_val is not None else (f"{value:.1f}" if value is not None else "--")
        if txt_main:
            text_color = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
            tw = draw.textbbox((0, 0), txt_main, font=_c_font)[2]
            ox = int(round(cfg.get("text_offset_x", 0.0) * out_gauge_size))
            oy = int(round(cfg.get("text_offset_y", 0.0) * out_gauge_size))
            px = _cx - tw // 2 + ox
            py = _cy + int(radius * 0.15 / ss) + oy
            if compose_5q_optimized():
                # ETAP 5Q: value-keyed centre-text tile cache (byte-exact
                # src-over; tile pixels reproduce the direct draw exactly).
                text_key = _static_cache_key(
                    "gauge_value_text", txt_main, _c_font,
                    text_color, outline,
                )
                cached = _STATIC_CACHE.get(text_key)
                if cached is None:
                    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
                    sl, st, sr, sb = probe.textbbox(
                        (0, 0), txt_main, font=_c_font,
                        stroke_width=max(1, outline),
                    )
                    tile = Image.new(
                        "RGBA", (max(1, sr - sl), max(1, sb - st)), (0, 0, 0, 0)
                    )
                    tdraw = ImageDraw.Draw(tile)
                    tdraw.text(
                        (-sl, -st), txt_main, font=_c_font,
                        fill=(text_color[0], text_color[1], text_color[2], 255),
                        stroke_width=max(1, outline), stroke_fill=(0, 0, 0, 255),
                    )
                    cached = (tile, sl, st)
                    _STATIC_CACHE[text_key] = cached
                tile, sl, st = cached
                img.alpha_composite(tile, (px + sl, py + st))
                # ETAP 2C: exact dynamic support = composited tile rectangle
                # (tile pixels are byte-exact, so no margin is required).
                _text_support = (
                    float(px + sl), float(py + st),
                    float(px + sl + tile.width),
                    float(py + st + tile.height))
            else:
                draw.text(
                    (px, py), txt_main, font=_c_font,
                    fill=(text_color[0], text_color[1], text_color[2], 255),
                    stroke_width=max(1, outline), stroke_fill=(0, 0, 0, 255),
                )
                # ETAP 2C: dynamic support measured with the same metrics PIL
                # used to rasterize the text above (probe-only cost; this
                # non-cached path runs on CPU-reference builds only).
                _tb_probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
                _tb = _tb_probe.textbbox(
                    (px, py), txt_main, font=_c_font,
                    stroke_width=max(1, outline))
                _text_support = (
                    float(_tb[0]), float(_tb[1]),
                    float(_tb[2]), float(_tb[3]))

    # ── ETAP 2C: report dynamic-support geometry to the AMD exporter ──────
    # Purely informational (never affects pixels). The exporter derives AUTO
    # upload rectangles for the persistent AFTER-MAP GPU gauge texture from
    # these bboxes: needle triangle sweep band ∪ composited value-text box,
    # each unioned with the previous frame's supports so moved elements are
    # erased by fresh crop bytes instead of ghosting over stale art.
    _needle_support = None
    if draw_needle:
        _n_hw = needle_width_px / 2.0
        _nvx = (base_x + pdx * _n_hw, base_x - pdx * _n_hw, tip_x)
        _nvy = (base_y + pdy * _n_hw, base_y - pdy * _n_hw, tip_y)
        _n_margin = 2.0  # PIL polygon rasterizer rounding margin
        _needle_support = (
            min(_nvx) - _n_margin, min(_nvy) - _n_margin,
            max(_nvx) + _n_margin, max(_nvy) + _n_margin)
    # Signature of every style/geometry parameter deciding which pixels are
    # static vs dynamic and where they sit inside the widget image. Any
    # change => new epoch => full-tile upload + region recompute.
    _sig_2c = (
        tuple(img.size), out_gauge_size, img_size,
        start_deg, sweep_deg, display_min, display_max,
        ticks, thickness, ss, gauge_fs, str(font_path), outline,
        pixel_profile, needle_len_rel, needle_width_px, needle_fill,
        show_marker, marker_size, bool(show_value),
        str(cfg.get("text_color", "#FFFFFF")),
        float(cfg.get("text_offset_x", 0.0)),
        float(cfg.get("text_offset_y", 0.0)),
        bool(compose_5q_optimized()),
        float(cfg.get("opacity", 1.0)),
        int(cfg.get("rotation", 0)) % 360,
    )
    record_gauge_dynamic_info(
        key, kind="speed", supported=True,
        rotation=int(cfg.get("rotation", 0)) % 360,
        widget_size=tuple(img.size),
        needle_bbox=_needle_support,
        text_bbox=_text_support,
        sig=_sig_2c)
    return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
