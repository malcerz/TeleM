"""Segment-bar indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import load_font, parse_hex_color, s


def _render_segment_bar_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    """Render a segment-bar indicator."""
    ss = max(1, ss)

    bar_w = int(cfg.get("width", 250)) * ss
    bar_h = int(cfg.get("height", 50)) * ss
    segments = max(1, int(cfg.get("segments", 20)))
    gap = int(cfg.get("segment_gap", 2)) * ss
    radius_seg = int(cfg.get("segment_radius", 2)) * ss

    total_gap = (segments - 1) * gap
    if total_gap >= bar_w:
        gap = 0
        total_gap = 0

    min_value = float(cfg.get("min_val", 0))
    max_value = float(cfg.get("max_val", 100))
    show_value = bool(cfg.get("show_value", True))
    show_min = bool(cfg.get("show_min", False))
    show_max = bool(cfg.get("show_max", False))
    show_label = bool(cfg.get("show_label", False))
    decimals = int(cfg.get("decimals", 0))
    label_text = str(label)
    direction = cfg.get("direction", "horizontal")
    grow_height = bool(cfg.get("grow_height", True))
    inactive_alpha = int(cfg.get("inactive_alpha", 100))
    gradient = cfg.get("gradient", ["#00FF00", "#FFFF00", "#FF0000"])
    inactive_color = parse_hex_color(cfg.get("inactive_color", "#404040")) or (64, 64, 64)

    frac = 0
    if max_value > min_value:
        frac = max(0, min(1, (value - min_value) / (max_value - min_value)))
    active_segments = round(frac * segments)

    min_str = f"{min_value:.{decimals}f}" if decimals else f"{min_value:.0f}"
    max_str = f"{max_value:.{decimals}f}" if decimals else f"{max_value:.0f}"
    val_str = formatted_val if formatted_val is not None else (f"{value:.{decimals}f}" if decimals else f"{value:.0f}")

    from src.indicators.helpers import _STATIC_CACHE, _static_cache_key

    cfg_str = str(sorted(cfg.items()))
    global_cfg_str = str(sorted(layout.get("global", {}).items()))

    cache_key = _static_cache_key(
        "segment_bar", canvas_w, canvas_h, font_path, key, active_segments,
        min_str, max_str, val_str, label_text, cfg_str, global_cfg_str, ss
    )
    px_x = s(cfg["x"], canvas_w)
    px_y = s(cfg["y"], canvas_h)
    cached = _STATIC_CACHE.get(cache_key)
    if cached is not None:
        return cached, px_x, px_y, None

    img = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def lerp_color(a, b, t):
        return a + (b - a) * t

    def gradient_color(position):
        if len(gradient) == 1:
            c = parse_hex_color(gradient[0])
            return c if c else (255, 255, 255)
        pos = max(0.0, min(1.0, position))
        step = 1.0 / (len(gradient) - 1)
        idx = min(len(gradient) - 2, int(pos / step))
        local_t = (pos - idx * step) / step
        c1 = parse_hex_color(gradient[idx]) or (255, 255, 255)
        c2 = parse_hex_color(gradient[idx + 1]) or (255, 255, 255)
        return (int(lerp_color(c1[0], c2[0], local_t)),
                int(lerp_color(c1[1], c2[1], local_t)),
                int(lerp_color(c1[2], c2[2], local_t)))

    seg_fs = max(8, int(bar_h * 0.22))
    label_top_space = seg_fs + 4 if (show_label and label_text) else 0
    seg_area_h = bar_h - label_top_space

    if direction == "horizontal":
        seg_w = (bar_w - total_gap) / segments
        for i in range(segments):
            seg_frac = i / (segments - 1) if segments > 1 else 0
            h_mult = 0.35 + seg_frac * 0.65 if grow_height else 1.0
            seg_height = max(1, int(seg_area_h * h_mult))
            x1 = int(i * (seg_w + gap))
            x2 = int(x1 + seg_w)
            y1, y2 = bar_h - seg_height, bar_h
            if i < active_segments:
                rgb = gradient_color(seg_frac)
                fill = (rgb[0], rgb[1], rgb[2], 255)
            else:
                fill = (inactive_color[0], inactive_color[1], inactive_color[2], inactive_alpha)
            draw.rounded_rectangle((x1, y1, x2, y2), radius=radius_seg, fill=fill)
    else:
        seg_h = (bar_h - label_top_space - total_gap) / segments
        for i in range(segments):
            seg_frac = i / (segments - 1) if segments > 1 else 0
            w_mult = 0.35 + seg_frac * 0.65 if grow_height else 1.0
            seg_width = max(1, int(bar_w * w_mult))
            y2 = bar_h - int(i * (seg_h + gap))
            y1 = int(y2 - seg_h)
            x1, x2 = 0, seg_width
            if i < active_segments:
                rgb = gradient_color(seg_frac)
                fill = (rgb[0], rgb[1], rgb[2], 255)
            else:
                fill = (inactive_color[0], inactive_color[1], inactive_color[2], inactive_alpha)
            draw.rounded_rectangle((x1, y1, x2, y2), radius=radius_seg, fill=fill)

    # ── Text labels ──
    if show_label or show_value or show_min or show_max:
        try:
            seg_font = load_font(font_path, seg_fs)
        except Exception:
            seg_font = font
        seg_outline = max(1, seg_fs // 12)
        txt_color_rgb = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
        txt_color = (txt_color_rgb[0], txt_color_rgb[1], txt_color_rgb[2], 255)
        dim_color = (180, 180, 180, 255)

    y_bottom, x_margin = bar_h - seg_fs - 2, 4

    if show_label and label_text:
        tw = draw.textbbox((0, 0), label_text, font=seg_font)[2]
        draw.text(((bar_w - tw) // 2, 2), label_text, font=seg_font,
                  fill=txt_color, stroke_width=seg_outline, stroke_fill=(0, 0, 0, 255))

    # min_str, max_str, val_str computed early for caching

    if show_min:
        draw.text((x_margin, y_bottom), min_str, font=seg_font,
                  fill=dim_color, stroke_width=seg_outline, stroke_fill=(0, 0, 0, 255))
    if show_max:
        tw_max = draw.textbbox((0, 0), max_str, font=seg_font)[2]
        draw.text((bar_w - tw_max - x_margin, y_bottom), max_str, font=seg_font,
                  fill=dim_color, stroke_width=seg_outline, stroke_fill=(0, 0, 0, 255))
    if show_value:
        tw_val = draw.textbbox((0, 0), val_str, font=seg_font)[2]
        if show_min and show_max:
            tw_min = draw.textbbox((0, 0), min_str, font=seg_font)[2]
            tw_max = draw.textbbox((0, 0), max_str, font=seg_font)[2]
            center = bar_w // 2
            value_x = max(x_margin + tw_min + 4, center - tw_val // 2)
            value_x = min(value_x, bar_w - tw_max - tw_val - x_margin - 4)
        elif show_max:
            tw_max = draw.textbbox((0, 0), max_str, font=seg_font)[2]
            value_x = bar_w - tw_max - tw_val - x_margin - 4
        else:
            value_x = bar_w - tw_val - x_margin
        draw.text((max(x_margin, value_x), y_bottom), val_str, font=seg_font,
                  fill=txt_color, stroke_width=seg_outline, stroke_fill=(0, 0, 0, 255))

    # ── Shadow (fast offset + alpha, no GaussianBlur) ──
    alpha = img.split()[3].point(lambda v: int(v * 0.35))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste(img, (2 * ss, 2 * ss))
    shadow.putalpha(alpha)
    img = Image.alpha_composite(shadow, img)

    if ss > 1:
        img = img.resize((int(bar_w / ss), int(bar_h / ss)), Image.LANCZOS)
    _STATIC_CACHE[cache_key] = img
    return img, px_x, px_y, None
