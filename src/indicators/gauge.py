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
    load_font,
    parse_hex_color,
    s,
)


def _render_gauge_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    """Render a gauge-form indicator (background cached)."""
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

    display_max = float(math.ceil(raw_max / 10.0) * 10)
    if display_max <= display_min:
        display_max = display_min + 10.0

    span = display_max - display_min
    if span <= 0:
        span = 10.0
        display_max = display_min + span

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

    major_intervals = max(1, int(round(span / step_val)))
    sub_ticks_count = max(1, ticks) if ticks > 0 else 10
    total_ticks = major_intervals * sub_ticks_count

    # ── Static background: tick marks + numbers (cached) ──
    bg_key = _static_cache_key(
        "gauge_bg", img_size, start_deg, sweep_deg,
        display_min, display_max, ticks, thickness, ss, gauge_fs, font_path, outline,
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
                tick_len = thickness * 0.9 * ss
                tick_width = max(2 * ss, int(thickness * 0.5) * ss)
            else:
                # Mniejsza i cieńsza kreska (sub-tick)
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

    frac = max(0, min(1, (value - display_min) / (display_max - display_min))) if display_max > display_min else 0
    ang = math.radians(start_deg + (end_deg - start_deg) * frac)

    # Needle
    needle_len_rel = cfg.get("needle_length", 1.1)
    needle_r_out = max(2, int(radius * needle_len_rel / (1 if ss > 1 else 1)))
    needle_r_in = max(1, int(radius * 0.05))
    needle_width_px = max(2, int(cfg.get("needle_width", 4) * 1.5))
    needle_rgb = parse_hex_color(cfg.get("needle_color", "#DC3232")) or (220, 50, 50)
    needle_fill = (needle_rgb[0], needle_rgb[1], needle_rgb[2], 255)

    # For cached bg we downscaled, so coordinates are in output space
    _cx, _cy = out_gauge_size // 2, out_gauge_size // 2
    pdx, pdy = -math.sin(ang), math.cos(ang)
    tip_x = _cx + math.cos(ang) * needle_r_out
    tip_y = _cy + math.sin(ang) * needle_r_out
    base_x = _cx + math.cos(ang) * needle_r_in
    base_y = _cy + math.sin(ang) * needle_r_in

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

    # Center text
    show_value = cfg.get("show_value", True)
    _fs_ds = max(8, fs)
    _c_font = load_font(font_path, _fs_ds)
    if key == "speed_visual" and label:
        tw = draw.textbbox((0, 0), label, font=_c_font)[2]
        ox = int(round(cfg.get("text_offset_x", 0.0) * out_gauge_size))
        oy = int(round(cfg.get("text_offset_y", 0.0) * out_gauge_size))
        draw.text(
            (_cx - tw // 2 + ox, _cy + int(radius * 0.15 / ss) + oy),
            label, font=_c_font,
            fill=(255, 255, 255, 255),
            stroke_width=max(1, outline), stroke_fill=(0, 0, 0, 255),
        )
    elif show_value:
        txt_main = formatted_val if formatted_val is not None else f"{value:.1f}"
        if txt_main:
            text_color = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
            tw = draw.textbbox((0, 0), txt_main, font=_c_font)[2]
            ox = int(round(cfg.get("text_offset_x", 0.0) * out_gauge_size))
            oy = int(round(cfg.get("text_offset_y", 0.0) * out_gauge_size))
            draw.text(
                (_cx - tw // 2 + ox, _cy + int(radius * 0.15 / ss) + oy),
                txt_main, font=_c_font,
                fill=(text_color[0], text_color[1], text_color[2], 255),
                stroke_width=max(1, outline), stroke_fill=(0, 0, 0, 255),
            )

    return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
