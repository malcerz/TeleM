"""Overlay renderer – PIL-based HUD overlay compositing functions.

This module contains all rendering functions for the TeleM telemetry overlay:
charts, gauges, bars, text indicators, time blocks, and custom texts.

Every function is a pure transformation: parameters in, PIL.Image out.
"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
    # Fallback if PIL is not available
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFilter = None  # type: ignore
    ImageFont = None  # type: ignore

# ── Font cache ──────────────────────────────────────────────────────────────

FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


# ── Helpers ─────────────────────────────────────────────────────────────────


def load_font_cache_small(size: int) -> Optional[ImageFont.ImageFont]:
    """Return the default PIL font at the given size (cached). Used for chart axis labels."""
    key = ("__builtin_default__", int(size))
    if key in FONT_CACHE:
        return FONT_CACHE[key]  # type: ignore[return-value]
    try:
        font = ImageFont.load_default()
        FONT_CACHE[key] = font
        return font
    except Exception:
        return None


def parse_hex_color(hex_str: Any) -> Optional[tuple[int, int, int]]:
    """Convert a hex colour string (e.g. '#FF3232' or 'FF3232') to an RGB tuple.
    Returns None on failure."""
    if not hex_str or not isinstance(hex_str, str):
        return None
    s = hex_str.strip().lstrip("#")
    try:
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        elif len(s) == 3:
            return (int(s[0], 16) * 17, int(s[1], 16) * 17, int(s[2], 16) * 17)
    except Exception:
        pass
    return None


def _parse_marker_color(hex_color: str) -> tuple[int, int, int, int]:
    """Convert '#RRGGBB' or '#RRGGBBAA' hex to RGBA tuple.
    Falls back to white on failure."""
    if not hex_color or not isinstance(hex_color, str):
        return (255, 255, 255, 255)
    s = hex_color.strip().lstrip("#")
    try:
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)
        elif len(s) == 8:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
    except Exception:
        pass
    return (255, 255, 255, 255)


def s(value: float, base: int) -> int:
    """Scale a relative value (0.0-1.0 range) to an absolute pixel size."""
    return max(1, int(round(value * base)))


def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font from cache or disk. Falls back to default PIL font on failure."""
    key = (str(font_path), int(size))
    font = FONT_CACHE.get(key)
    if font is not None:
        return font
    try:
        font = ImageFont.truetype(str(font_path), size=int(size))
    except Exception:
        font = ImageFont.load_default()
    FONT_CACHE[key] = font
    return font


# ── Chart rendering ─────────────────────────────────────────────────────────


def generate_history_chart(
    history_values: list[float],
    width: int,
    height: int,
    line_color: tuple[int, int, int] = (255, 0, 0),
    line_thickness: int = 3,
    fill_alpha: int = 50,
    fill_color: Optional[tuple[int, int, int]] = None,
    current_index: Optional[int] = None,
    cursor_color: tuple[int, int, int] = (255, 255, 255),
    show_axes: bool = True,
    time_labels: Optional[list[str]] = None,
    value_labels: Optional[list[str]] = None,
    supersample: int = 1,
) -> Image.Image:
    """Generate a universal line chart with transparent fill, axes, and optional cursor.

    Args:
        history_values: Data points to plot.
        width: Output image width in pixels.
        height: Output image height in pixels.
        line_color: RGB tuple for the main line.
        line_thickness: Width of the main line.
        fill_alpha: Fill transparency (0-255).
        fill_color: Optional separate fill colour (defaults to line_color).
        current_index: Index of the cursor position (None = no cursor).
        cursor_color: RGB for the cursor line.
        show_axes: Whether to draw axes with labels.
        time_labels: 5 strings for X-axis labels.
        value_labels: Strings for Y-axis labels (defaults to [min, max]).
        supersample: Render at Nx resolution then downscale for anti-aliasing (1=off).

    Returns:
        RGBA PIL.Image.
    """
    ss = max(1, int(supersample))
    out_w, out_h = width, height
    width *= ss
    height *= ss
    line_thickness *= ss
    axis_left_margin = (50 if show_axes else 0) * ss
    axis_bottom_margin = (22 if show_axes else 0) * ss
    axis_top_margin = 4 * ss
    axis_right_margin = 4 * ss

    has_data = history_values and len(history_values) >= 2

    if has_data:
        min_val = float(min(history_values))
        max_val = float(max(history_values))
    else:
        min_val = 0.0
        max_val = 100.0
    val_range = max_val - min_val
    if val_range == 0:
        val_range = 1.0

    num_points = len(history_values) if has_data else 0

    plot_x1 = axis_left_margin
    plot_y1 = axis_top_margin
    plot_x2 = width - axis_right_margin
    plot_y2 = height - axis_bottom_margin
    plot_w = plot_x2 - plot_x1
    plot_h = plot_y2 - plot_y1
    if plot_w <= 0:
        plot_w = 1
    if plot_h <= 0:
        plot_h = 1

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if show_axes:
        axis_color = (180, 180, 180, 220)
        tick_color = (150, 150, 150, 200)
        label_color = (200, 200, 200, 240)

        draw.line((plot_x1, plot_y1, plot_x1, plot_y2), fill=axis_color, width=1)
        draw.line((plot_x1, plot_y2, plot_x2, plot_y2), fill=axis_color, width=1)

        try:
            font_axis = load_font_cache_small(10)
        except Exception:
            font_axis = None

        y_label_values = value_labels if value_labels else [f"{min_val:.0f}", f"{max_val:.0f}"]
        y_positions = [plot_y2, plot_y1]

        for i, (lbl, yp) in enumerate(zip(y_label_values, y_positions)):
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            else:
                tw = len(lbl) * 6
                th = 10
            tx = plot_x1 - tw - 5
            ty = yp - th // 2
            if font_axis:
                draw.text((tx, ty), lbl, fill=label_color, font=font_axis)
            else:
                draw.text((tx, ty), lbl, fill=label_color)

        draw.line((plot_x1 - 4, plot_y2, plot_x1, plot_y2), fill=tick_color, width=1)
        draw.line((plot_x1 - 4, plot_y1, plot_x1, plot_y1), fill=tick_color, width=1)

        x_labels = time_labels if time_labels else ["0%", "25%", "50%", "75%", "100%"]
        for i, lbl in enumerate(x_labels):
            x = plot_x1 + (plot_w * i / max(1, len(x_labels) - 1))
            draw.line((x, plot_y2, x, plot_y2 + 4), fill=tick_color, width=1)
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                tw = bbox[2] - bbox[0]
            else:
                tw = len(lbl) * 6
            tx = x - tw // 2
            ty = plot_y2 + 5
            if font_axis:
                draw.text((tx, ty), lbl, fill=label_color, font=font_axis)
            else:
                draw.text((tx, ty), lbl, fill=label_color)

    if not has_data:
        return img

    # Calculate point coordinates
    points: list[tuple[float, float]] = []
    for i, val in enumerate(history_values):
        x = plot_x1 + (i / (num_points - 1)) * plot_w
        v_margin = line_thickness + 1
        usable_h = plot_h - (2 * v_margin)
        y = plot_y2 - v_margin - ((val - min_val) / val_range) * usable_h
        points.append((x, y))

    # Fill under the line
    fill_polygon: list[tuple[float, float]] = list(points)
    fill_polygon.append((plot_x2, plot_y2))
    fill_polygon.append((plot_x1, plot_y2))
    actual_fill_rgb = fill_color if fill_color is not None else line_color
    actual_fill = (actual_fill_rgb[0], actual_fill_rgb[1], actual_fill_rgb[2], fill_alpha)

    fill_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill_img)
    fill_draw.polygon(fill_polygon, fill=actual_fill)  # type: ignore[arg-type]
    img = Image.alpha_composite(img, fill_img)

    # Draw the line
    draw = ImageDraw.Draw(img)
    draw.line(points, fill=(line_color[0], line_color[1], line_color[2], 255), width=line_thickness, joint="round")

    # Draw cursor
    if current_index is not None and 0 <= current_index < num_points:
        cursor_x = points[current_index][0]
        draw.line(
            (cursor_x, plot_y1, cursor_x, plot_y2),
            fill=(cursor_color[0], cursor_color[1], cursor_color[2], 200),
            width=max(2, line_thickness),
        )
        py = points[current_index][1]
        dot_r = max(3, line_thickness + 1)
        draw.ellipse(
            (cursor_x - dot_r, py - dot_r, cursor_x + dot_r, py + dot_r),
            fill=(cursor_color[0], cursor_color[1], cursor_color[2], 255),
            outline=(line_color[0], line_color[1], line_color[2], 255),
        )

    if ss > 1:
        img = img.resize((out_w, out_h), Image.LANCZOS)
    return img


# ── Single-indicator rendering ──────────────────────────────────────────────


def render_custom_text(
    canvas_w: int, canvas_h: int, font_path: str, cfg: dict[str, Any],
    stroke_width: int = 2,
) -> tuple[Optional[Image.Image], int, int]:
    """Render a single custom text overlay.

    Args:
        canvas_w: Canvas width in pixels.
        canvas_h: Canvas height in pixels.
        font_path: Path to the TrueType font file.
        cfg: Dict with keys: enabled, text, x, y, rotation, font_size, color.
        stroke_width: Outline thickness in pixels (default 2).

    Returns:
        (overlay_img, px_x, px_y) or (None, 0, 0) if disabled.
    """
    if not cfg.get("enabled", True):
        return None, 0, 0
    text = str(cfg.get("text", ""))
    if not text:
        return None, 0, 0
    min_dim = min(canvas_w, canvas_h)
    font_size_px = max(8, int(round(cfg.get("font_size", 0.03) * min_dim)))
    font = load_font(font_path, font_size_px)
    color_hex = cfg.get("color", "#FFFFFF")
    rgb = parse_hex_color(color_hex)
    if rgb is None:
        rgb = (255, 255, 255)
    fill_color = (rgb[0], rgb[1], rgb[2], 255)
    tmp = Image.new("RGBA", (canvas_w, font_size_px * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    overlay = Image.new("RGBA", (tw + 8, th + 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.text((4, 4), text, font=font, fill=fill_color, stroke_width=stroke_width, stroke_fill=(0, 0, 0, 200))
    px = int(round(cfg.get("x", 0.5) * canvas_w))
    py = int(round(cfg.get("y", 0.5) * canvas_h))
    return overlay, px, py


def rotated_paste(
    base_img: Image.Image,
    overlay: Image.Image,
    center_x: int,
    center_y: int,
    rotation: int,
) -> None:
    """Paste *overlay* onto *base_img* centred at (center_x, center_y) with rotation.
    Modifies base_img in place."""
    rotation = int(rotation) % 360
    if rotation == 90:
        overlay = overlay.transpose(Image.Transpose.ROTATE_90)
    elif rotation == 180:
        overlay = overlay.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        overlay = overlay.transpose(Image.Transpose.ROTATE_270)
    x = int(round(center_x - overlay.width / 2))
    y = int(round(center_y - overlay.height / 2))
    base_img.alpha_composite(overlay, (x, y))


def render_time_block(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    date_text: str,
    time_text: str,
) -> tuple[Optional[Image.Image], int, int]:
    """Render the date/time block indicator.

    Returns:
        (overlay_img, px_x, px_y) or (None, 0, 0) if disabled or missing.
    """
    cfg = layout.get("indicators", {}).get("time_block")
    if cfg is None or not cfg.get("enabled", True):
        return None, 0, 0

    min_dim = min(canvas_w, canvas_h)
    outline_raw = int(layout["global"].get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))

    label_px = max(12, s(cfg["font_label"], min_dim))
    date_px = max(14, s(cfg["font_date"], min_dim))
    time_px = max(14, s(cfg["font_time"], min_dim))

    font_label = load_font(font_path, label_px)
    font_date = load_font(font_path, date_px)
    font_time = load_font(font_path, time_px)

    tmp = Image.new(
        "RGBA",
        (max(200, s(0.25, canvas_w)), max(100, s(0.12, canvas_h))),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(tmp)

    y = 0
    draw.text(
        (0, y),
        cfg.get("label", "Czas"),
        font=font_label,
        fill=(210, 210, 210, 255),
        stroke_width=outline,
        stroke_fill=(0, 0, 0, 255),
    )
    y += int(label_px * 1.3)

    draw.text(
        (0, y),
        date_text,
        font=font_date,
        fill=(255, 255, 255, 255),
        stroke_width=outline,
        stroke_fill=(0, 0, 0, 255),
    )
    y += int(date_px * 1.2)

    draw.text(
        (0, y),
        time_text,
        font=font_time,
        fill=(255, 255, 255, 255),
        stroke_width=outline,
        stroke_fill=(0, 0, 0, 255),
    )

    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0

    return tmp.crop(bbox), s(cfg["x"], canvas_w), s(cfg["y"], canvas_h)


def render_value_indicator(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    key: str,
    value: float,
    unit: str,
    label: str,
    cfg_override: Optional[dict[str, Any]] = None,
    formatted_val: Optional[str] = None,
    max_distance_m: Optional[float] = None,
    history_data: Optional[list[float] | dict[str, Any]] = None,
    current_position: Optional[float] = None,
    gps_track: Optional[list[tuple[Any, float, float]]] = None,
    supersample: int = 1,
    target_dt: Optional[datetime] = None,
    start_dt_utc: Optional[datetime] = None,
) -> tuple[Optional[Image.Image], int, int, Optional[dict[str, Any]]]:
    """Render a single telemetry indicator (text, gauge, bar, or chart form).

    Args:
        canvas_w, canvas_h: Canvas dimensions.
        layout: Full HUD layout dict.
        font_path: Path to TrueType font.
        key: Indicator key (e.g. "speed_text").
        value: Current value to display.
        unit: Unit string (e.g. "km/h").
        label: Display label.
        cfg_override: Optional config override (uses layout config if None).
        formatted_val: Pre-formatted value string (auto-built if None).
        max_distance_m: Max distance for bar range labels.
        history_data: Chart data (list of floats or dict with 'values' key).
        current_position: 0.0-1.0 position for chart cursor.
        supersample: Supersampling factor (default 1).

    Returns:
        (overlay_img, px_x, px_y, extra_dict) or (None, 0, 0, None) if disabled.
    """
    cfg = cfg_override if cfg_override else layout["indicators"].get(key)
    if not cfg or not cfg.get("enabled", True):
        return None, 0, 0, None

    form = cfg.get("form", "text")
    _FORM_MAP = {"TEXT": "text", "SUWAK": "bar", "LICZNIK": "text"}
    form = _FORM_MAP.get(form, form)
    min_dim = min(canvas_w, canvas_h)
    outline_raw = int(layout["global"].get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    fs = max(8, s(cfg.get("font_size", 0.02), min_dim))
    font = load_font(font_path, fs)

    val_min = float(cfg.get("min_val", 0))
    val_max = float(cfg.get("max_val", 100))
    ticks = int(cfg.get("ticks", 0))
    # thickness: new format (1-10) → convert to old relative for s() scaling;
    # old format (< 1) → use as-is for backward compat
    _thickness_raw = float(cfg.get("thickness", 1))
    if _thickness_raw >= 1:
        _thickness_rel = _thickness_raw / 200.0
    else:
        _thickness_rel = _thickness_raw
    thickness = max(1, s(_thickness_rel, min_dim))
    size_px = s(cfg.get("size", 0.1), min_dim if form == "gauge" else canvas_w)
    ss = max(1, supersample)

    if form == "text":
        v_str = formatted_val if formatted_val else f"{value:.1f} {unit}"
        txt = f"{label}: {v_str}" if label else v_str
        tmp = Image.new("RGBA", (canvas_w, fs * 3), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tmp)
        draw.text(
            (0, 0),
            txt,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=outline,
            stroke_fill=(0, 0, 0, 255),
        )
        bbox = tmp.getbbox()
        if not bbox:
            return None, 0, 0, None
        return tmp.crop(bbox), s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None

    elif form == "bar":
        # Apply supersampling to bar dimensions
        w, h = int(size_px * ss), int(max(24, thickness * 6) * ss)
        img = Image.new("RGBA", (w + 40 * ss, h + 30 * ss), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        v_str = f"{value:.1f} {unit}"
        show_value = cfg.get("show_value", True)

        if label:
            draw.text(
                (20 * ss, 0),
                label,
                font=font,
                fill=(210, 210, 210, 255),
                stroke_width=outline,
                stroke_fill=(0, 0, 0, 255),
            )

        by = h - thickness - 5 * ss
        x1, x2 = 20 * ss, w + 20 * ss
        draw.line((x1, by, x2, by), fill=(160, 160, 160, 180), width=thickness * ss)

        if ticks > 1:
            for i in range(ticks + 1):
                xt = x1 + (w * i / ticks)
                draw.line(
                    (xt, by - thickness * ss, xt, by + thickness * ss),
                    fill=(245, 245, 245, 220),
                    width=max(1, thickness // 4 * ss),
                )

        frac = max(0, min(1, (value - val_min) / (val_max - val_min))) if val_max > val_min else 0
        dot_x = x1 + frac * w
        dot_y = by

        draw.ellipse(
            (dot_x - thickness * ss, dot_y - thickness * ss, dot_x + thickness * ss, dot_y + thickness * ss),
            fill=(255, 50, 50, 255),
            outline=(255, 255, 255, 255),
        )
        extra = {
            "show_value": show_value,
            "value_text": v_str,
            "dot_x": dot_x / ss,
            "dot_y": dot_y / ss,
            "bar_w": w / ss,
            "bar_h": h / ss,
            "x1": x1 / ss,
            "x2": x2 / ss,
            "by": by / ss,
            "show_range_labels": cfg.get("show_range_labels", False),
            "left_text": f"{cfg.get('min_val', 0):.0f}",
            "right_text": f"{cfg.get('max_val', 100):.0f}",
        }
        # Downscale to original size
        if ss > 1:
            img = img.resize((int(img.width / ss), int(img.height / ss)), Image.LANCZOS)
        return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), extra

    elif form == "gauge":
        # Force minimum 3× supersampling – PIL ImageDraw has no native AA,
        # so we must render larger and downscale for smooth edges.
        ss = max(3, ss)

        gauge_fs = max(8, fs * ss)
        gauge_font = load_font(font_path, gauge_fs)
        gauge_outline = outline * ss

        radius = size_px * ss
        img_size = int(radius * 2.4)

        out_gauge_size = int(size_px * 2.4)

        img = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        cx = cy = img_size // 2

        start_deg, end_deg = 180, 360

        display_min = 0
        display_max = math.ceil(val_max / 10.0) * 10 if val_max > 0 else 10

        major_ticks_count = int(display_max / 10)
        if major_ticks_count < 1:
            major_ticks_count = 1

        sub_ticks_count = max(1, ticks) if ticks > 0 else 10
        total_ticks = major_ticks_count * sub_ticks_count

        # ---------------------------------------------------------
        # PODZIAŁKA
        # ---------------------------------------------------------

        for i in range(total_ticks + 1):
            a = math.radians(
                start_deg + (end_deg - start_deg) * i / total_ticks
            )

            cos_a = math.cos(a)
            sin_a = math.sin(a)

            if i % sub_ticks_count == 0:
                tick_len = thickness * ss
                tick_width = max(3 * ss, int(thickness // 3) * ss)

                tick_val = (
                    display_min
                    + (display_max - display_min) * (i / total_ticks)
                )

                txt_tick = f"{tick_val:.0f}"

                text_radius = radius - tick_len - (radius * 0.20)

                tx = cx + cos_a * text_radius
                ty = cy + sin_a * text_radius

                draw.text(
                    (tx, ty),
                    txt_tick,
                    font=gauge_font,
                    fill=(255, 255, 255, 240),
                    stroke_width=ss,
                    stroke_fill=(0, 0, 0, 255),
                    anchor="mm",
                )

            elif i % (sub_ticks_count // 2) == 0:
                tick_len = thickness * 0.7 * ss
                tick_width = max(2 * ss, int(thickness // 4) * ss)

            else:
                tick_len = thickness * 0.4 * ss
                tick_width = max(1 * ss, int(thickness // 6) * ss)

            r_out = radius
            r_in = radius - tick_len

            x1 = cx + cos_a * r_in
            y1 = cy + sin_a * r_in

            x2 = cx + cos_a * r_out
            y2 = cy + sin_a * r_out

            # wektor prostopadły
            px = -sin_a
            py = cos_a

            hw = tick_width / 2

            draw.polygon(
                [
                    (x1 + px * hw, y1 + py * hw),
                    (x1 - px * hw, y1 - py * hw),
                    (x2 - px * hw, y2 - py * hw),
                    (x2 + px * hw, y2 + py * hw),
                ],
                fill=(240, 240, 240, 255),
            )

        # ---------------------------------------------------------
        # WSKAZÓWKA
        # ---------------------------------------------------------

        frac = (
            max(
                0,
                min(
                    1,
                    (value - display_min)
                    / (display_max - display_min),
                ),
            )
            if display_max > display_min
            else 0
        )

        ang = math.radians(
            start_deg + (end_deg - start_deg) * frac
        )

        # Wskazówka
        needle_len_rel = cfg.get("needle_length", 1.1)
        needle_r_out = max(2 * ss, int(radius * needle_len_rel))
        needle_r_in = max(1, int(radius * 0.05))
        needle_width_px = max(
            2 * ss,
            int(cfg.get("needle_width", 4) * 1.5 * ss)
        )

        needle_color_hex = cfg.get("needle_color", "#DC3232")
        needle_rgb = parse_hex_color(needle_color_hex)
        if needle_rgb is None:
            needle_rgb = (220, 50, 50)
        needle_fill = (needle_rgb[0], needle_rgb[1], needle_rgb[2], 255)

        px = -math.sin(ang)
        py = math.cos(ang)

        tip_x = cx + math.cos(ang) * needle_r_out
        tip_y = cy + math.sin(ang) * needle_r_out

        base_x = cx + math.cos(ang) * needle_r_in
        base_y = cy + math.sin(ang) * needle_r_in

        draw.polygon(
            [
                (
                    base_x + px * needle_width_px / 2,
                    base_y + py * needle_width_px / 2,
                ),
                (
                    base_x - px * needle_width_px / 2,
                    base_y - py * needle_width_px / 2,
                ),
                (tip_x, tip_y),
            ],
            fill=needle_fill,
        )

        # Oś wskazówki
       
        # ---------------------------------------------------------
        # TEKST ŚRODKOWY
        # ---------------------------------------------------------

        show_value = cfg.get("show_value", True)

        if key == "speed_visual":
            if label:
                tw = draw.textbbox(
                    (0, 0),
                    label,
                    font=gauge_font,
                )[2]

                ox = int(round(cfg.get("text_offset_x", 0.0) * img_size))
                oy = int(round(cfg.get("text_offset_y", 0.0) * img_size))
                draw.text(
                    (cx - tw // 2 + ox, cy + int(radius * 0.15) + oy),
                    label,
                    font=gauge_font,
                    fill=(255, 255, 255, 255),
                    stroke_width=gauge_outline,
                    stroke_fill=(0, 0, 0, 255),
                )
        elif show_value:
            txt_main = f"{value:.1f}"

            tw = draw.textbbox(
                (0, 0),
                txt_main,
                font=gauge_font,
            )[2]

            ox = int(round(cfg.get("text_offset_x", 0.0) * img_size))
            oy = int(round(cfg.get("text_offset_y", 0.0) * img_size))
            draw.text(
                (cx - tw // 2 + ox, cy + int(radius * 0.15) + oy),
                txt_main,
                font=gauge_font,
                fill=(255, 255, 255, 255),
                stroke_width=gauge_outline,
                stroke_fill=(0, 0, 0, 255),
            )

        # ---------------------------------------------------------
        # SHADOW
        # ---------------------------------------------------------

        shadow_offset = max(
            2 * ss,
            int(radius * 0.025)
        )

        shadow = Image.new(
            "RGBA",
            img.size,
            (0, 0, 0, 0),
        )

        shadow.paste(
            img,
            (shadow_offset, shadow_offset),
        )

        alpha = shadow.split()[3].point(
            lambda x: int(x * 0.35)
        )

        alpha = alpha.filter(
            ImageFilter.GaussianBlur(
                radius=max(
                    ss,
                    int(radius * 0.035),
                )
            )
        )

        shadow_rgba = Image.new(
            "RGBA",
            img.size,
            (0, 0, 0, 0),
        )

        shadow_rgba.putalpha(alpha)

        img = Image.alpha_composite(
            shadow_rgba,
            img,
        )

        # ---------------------------------------------------------
        # FINAL ANTIALIASING
        # ---------------------------------------------------------

        if ss > 1:
            img = img.filter(
                ImageFilter.GaussianBlur(
                    radius=0.5 * ss
                )
            )

            img = img.resize(
                (
                    out_gauge_size,
                    out_gauge_size,
                ),
                Image.LANCZOS,
            )

        return (
            img,
            s(cfg["x"], canvas_w),
            s(cfg["y"], canvas_h),
            None,
        )

    elif form == "chart":
        time_labels = None
        chart_vals = None
        if isinstance(history_data, dict):
            chart_vals = history_data.get("values", [])
            time_labels = history_data.get("time_labels")
        elif isinstance(history_data, list):
            chart_vals = history_data

        if not chart_vals or len(chart_vals) < 2:
            chart_vals = [value, value]

        ci = None
        if current_position is not None:
            ci = int(round(current_position * (len(chart_vals) - 1)))
            ci = max(0, min(len(chart_vals) - 1, ci))

        chart_w = size_px
        chart_h = max(40, int(chart_w * 0.4))

        custom_color = parse_hex_color(cfg.get("chart_color", ""))
        if custom_color:
            line_clr = custom_color
        elif "speed" in key or "cad" in key:
            line_clr = (255, 50, 50)
        elif "alt" in key:
            line_clr = (50, 200, 50)
        elif "dist" in key:
            line_clr = (50, 150, 255)
        elif "power" in key:
            line_clr = (255, 200, 50)
        elif "hr" in key:
            line_clr = (255, 50, 150)
        elif "battery" in key:
            line_clr = (50, 255, 50)
        else:
            line_clr = (200, 200, 200)

        chart_fill_alpha = int(cfg.get("fill_alpha", 40))
        chart_fill_color = parse_hex_color(cfg.get("fill_color", ""))

        chart_img = generate_history_chart(
            chart_vals,
            chart_w,
            chart_h,
            line_color=line_clr,
            line_thickness=max(1, int(float(cfg.get("thickness", 1)))),
            fill_alpha=chart_fill_alpha,
            fill_color=chart_fill_color,
            current_index=ci,
            cursor_color=(255, 255, 255),
            show_axes=True,
            time_labels=time_labels,
            supersample=2,
        )

        margin_top = fs + 8 if label else 0
        final_h = chart_h + margin_top + 4
        final_img = Image.new("RGBA", (chart_w + 8, final_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(final_img)

        if label:
            draw.text(
                (4, 0),
                label,
                font=font,
                fill=(210, 210, 210, 255),
                stroke_width=outline,
                stroke_fill=(0, 0, 0, 255),
            )

        final_img.paste(chart_img, (4, margin_top), chart_img)

        v_str = formatted_val if formatted_val else f"{value:.1f} {unit}"
        bbox = draw.textbbox((0, 0), v_str, font=font)
        vw = bbox[2] - bbox[0]
        draw.text(
            (chart_w - vw, 0),
            v_str,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=outline,
            stroke_fill=(0, 0, 0, 255),
        )

        return final_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None

    elif form == "segment_bar":
        # Use existing supersampling factor; ensure at least 1×
        ss = max(1, ss)

        bar_w = int(cfg.get("width", 250)) * ss
        bar_h = int(cfg.get("height", 50)) * ss

        segments = max(1, int(cfg.get("segments", 20)))
        gap = int(cfg.get("segment_gap", 2)) * ss
        radius_seg = int(cfg.get("segment_radius", 2)) * ss

        # Clamp to prevent degenerate geometry
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
        inactive_color = parse_hex_color(cfg.get("inactive_color", "#404040"))
        if inactive_color is None:
            inactive_color = (64, 64, 64)

        img = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # --- gradient helpers ---
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
            c1 = parse_hex_color(gradient[idx])
            c2 = parse_hex_color(gradient[idx + 1])
            if c1 is None:
                c1 = (255, 255, 255)
            if c2 is None:
                c2 = (255, 255, 255)
            return (int(lerp_color(c1[0], c2[0], local_t)),
                    int(lerp_color(c1[1], c2[1], local_t)),
                    int(lerp_color(c1[2], c2[2], local_t)))

        # --- fill fraction ---
        frac = 0
        if max_value > min_value:
            frac = max(0, min(1, (value - min_value) / (max_value - min_value)))
        active_segments = round(frac * segments)

        # --- text labels (compute before geometry to reserve space) ---
        seg_fs = max(8, int(bar_h * 0.22))
        label_top_space = seg_fs + 4 if (show_label and label_text) else 0
        seg_area_h = bar_h - label_top_space  # usable height for segments

        # --- geometry ---
        if direction == "horizontal":
            seg_w = (bar_w - total_gap) / segments
            for i in range(segments):
                seg_frac = i / (segments - 1) if segments > 1 else 0
                h_mult = 0.35 + seg_frac * 0.65 if grow_height else 1.0
                seg_height = max(1, int(seg_area_h * h_mult))
                x1 = int(i * (seg_w + gap))
                x2 = int(x1 + seg_w)
                y1 = bar_h - seg_height
                y2 = bar_h
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
                x1 = 0
                x2 = seg_width
                if i < active_segments:
                    rgb = gradient_color(seg_frac)
                    fill = (rgb[0], rgb[1], rgb[2], 255)
                else:
                    fill = (inactive_color[0], inactive_color[1], inactive_color[2], inactive_alpha)
                draw.rounded_rectangle((x1, y1, x2, y2), radius=radius_seg, fill=fill)

        # --- text labels ---
        if show_label or show_value or show_min or show_max:
            try:
                seg_font = load_font(font_path, seg_fs)
            except Exception:
                seg_font = font
            seg_outline = max(1, seg_fs // 12)
            txt_color = (255, 255, 255, 255)
            dim_color = (180, 180, 180, 255)

        y_bottom = bar_h - seg_fs - 2
        x_margin = 4

        if show_label and label_text:
            tw = draw.textbbox((0, 0), label_text, font=seg_font)[2]
            draw.text(
                ((bar_w - tw) // 2, 2),
                label_text,
                font=seg_font,
                fill=txt_color,
                stroke_width=seg_outline,
                stroke_fill=(0, 0, 0, 255),
            )

        min_str = f"{min_value:.{decimals}f}" if decimals else f"{min_value:.0f}"
        max_str = f"{max_value:.{decimals}f}" if decimals else f"{max_value:.0f}"
        val_str = f"{value:.{decimals}f}" if decimals else f"{value:.0f}"

        if show_min:
            draw.text(
                (x_margin, y_bottom),
                min_str,
                font=seg_font,
                fill=dim_color,
                stroke_width=seg_outline,
                stroke_fill=(0, 0, 0, 255),
            )

        if show_max:
            tw_max = draw.textbbox((0, 0), max_str, font=seg_font)[2]
            draw.text(
                (bar_w - tw_max - x_margin, y_bottom),
                max_str,
                font=seg_font,
                fill=dim_color,
                stroke_width=seg_outline,
                stroke_fill=(0, 0, 0, 255),
            )

        if show_value:
            tw_val = draw.textbbox((0, 0), val_str, font=seg_font)[2]
            # Place between min and max, or at bottom-right if max is off
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
            draw.text(
                (max(x_margin, value_x), y_bottom),
                val_str,
                font=seg_font,
                fill=txt_color,
                stroke_width=seg_outline,
                stroke_fill=(0, 0, 0, 255),
            )

        # --- shadow ---
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow.paste(img, (2 * ss, 2 * ss))
        alpha = shadow.split()[3].point(lambda v: int(v * 0.35))
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius=2 * ss))
        shadow_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow_img.putalpha(alpha)
        img = Image.alpha_composite(shadow_img, img)

        # --- antialiasing ---
        if ss > 1:
            img = img.filter(ImageFilter.GaussianBlur(radius=0.35 * ss))
            img = img.resize((int(bar_w / ss), int(bar_h / ss)), Image.LANCZOS)

        return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None

    elif form == "static_map":
        if gps_track and len(gps_track) >= 2:
            try:
                from src.map_renderer import render_map_overlay, precache_map_tiles

                map_w = size_px
                map_h = max(40, int(map_w * 0.65))
                zoom = int(cfg.get("zoom", 16))
                map_style = cfg.get("map_style", "light_all")

                # Pre-cache wszystkich kafelków dla całej trasy w tle (jednorazowo)
                _pc_key = ("static_precache", id(gps_track), zoom, map_style)
                if not hasattr(render_value_indicator, "_static_map_precached"):
                    render_value_indicator._static_map_precached = set()
                if _pc_key not in render_value_indicator._static_map_precached:
                    render_value_indicator._static_map_precached.add(_pc_key)
                    threading.Thread(
                        target=precache_map_tiles,
                        args=(gps_track, zoom, map_style),
                        daemon=True,
                    ).start()

                if target_dt is not None:
                    import bisect
                    target_ts = target_dt.timestamp()
                    # Cache listy timestampów dla wydajności (buduj raz na zmianę gps_track)
                    cache_key = id(gps_track)
                    if (not hasattr(render_value_indicator, "_static_gps_times")
                            or render_value_indicator._static_gps_times_id != cache_key):
                        render_value_indicator._static_gps_times = [
                            (dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp())
                            for dt, _, _ in gps_track
                        ]
                        render_value_indicator._static_gps_times_id = cache_key
                    times = render_value_indicator._static_gps_times
                    ci = bisect.bisect_left(times, target_ts)
                    # Wybierz najbliższy z dwóch sąsiednich indeksów
                    if ci > 0 and ci < len(times) and abs(times[ci] - target_ts) > abs(times[ci - 1] - target_ts):
                        ci = ci - 1
                    ci = max(0, min(len(gps_track) - 1, ci))
                else:
                    # Fallback: stary sposób (current_position)
                    ci = int(round((current_position if current_position is not None else 0.0) * (len(gps_track) - 1)))
                    ci = max(0, min(len(gps_track) - 1, ci))

                map_img = render_map_overlay(
                    gps_track, ci, map_w, map_h,
                    zoom=zoom,
                    map_style=map_style,
                    marker_radius=int(cfg.get("marker_size", 7)),
                    marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
                    download_missing=False,
                )
                return map_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
            except Exception:
                # W razie błędu wpadamy do placeholdera
                pass

    elif form == "map":
        if gps_track and len(gps_track) >= 2:
            try:
                from src.moving_map import MovingMapRenderer

                # Cache renderer per-track (track + zoom + style = unique key)
                track_id = id(gps_track)
                zoom = int(cfg.get("zoom", 16))
                map_style = cfg.get("map_style", "light_all")
                cache_key = (track_id, zoom, map_style)
                if not hasattr(render_value_indicator, "_map_renderers"):
                    render_value_indicator._map_renderers = {}  # type: ignore[attr-defined]
                _cache = render_value_indicator._map_renderers  # type: ignore[attr-defined]
                if cache_key not in _cache:
                    renderer = MovingMapRenderer(
                        gps_track, zoom=zoom, style=map_style,
                        marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
                        marker_radius=int(cfg.get("marker_size", 7)),
                    )
                    _cache[cache_key] = renderer
                    # Uruchom w tle pobieranie kafelków dla całej trasy
                    # (rendering poniżej używa tylko cache'a, więc nie blokuje)
                    renderer.background_precache(margin=2)
                else:
                    renderer = _cache[cache_key]

                map_w = size_px
                map_h = max(40, int(map_w * 0.65))
                if target_dt is not None:
                    # ts = offset od PIERWSZEGO punktu GPS (zgodny z MovingMapRenderer._idx)
                    gps0 = gps_track[0][0]
                    if hasattr(gps0, 'timestamp'):
                        if gps0.tzinfo is None:
                            gps0_ts = gps0.replace(tzinfo=timezone.utc).timestamp()
                        else:
                            gps0_ts = gps0.timestamp()
                        ts = target_dt.timestamp() - gps0_ts
                    else:
                        ts = 0.0
                else:
                    # Fallback: znormalizowana pozycja (0-1) × długość trasy GPS
                    dur = (gps_track[-1][0].timestamp() - gps_track[0][0].timestamp())
                    ts = (current_position if current_position is not None else 0.0) * dur
                # Nie pobieraj kafelków podczas podglądu – tylko z cache'a
                map_img = renderer.render(ts, map_w, map_h, download_missing=False)
                return map_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
            except Exception:
                # Jeśli renderowanie mapy się nie powiedzie (brak netu, timeout,
                # błąd importu), wpadamy do placeholdera poniżej
                pass

    # Wspólny placeholder dla mapy (brak GPS lub za mało punktów)
    if form in ("map", "static_map"):
        z = int(cfg.get("zoom", 16))
        ph_w = size_px
        ph_h = max(60, int(ph_w * 0.65))
        ph = Image.new("RGBA", (ph_w, ph_h), (20, 20, 30, 220))
        draw = ImageDraw.Draw(ph)
        if not gps_track:
            msg = "Brak danych GPS w wideo"
        else:
            msg = f"GPS: {len(gps_track)} pkt (za malo)"
        draw.text((8, 8), msg, font=font, fill=(200, 200, 200, 255),
                  stroke_width=outline, stroke_fill=(0, 0, 0, 255))
        draw.text((8, 24 + fs), f"Zoom: {z}", font=font, fill=(160, 160, 160, 255))
        return ph, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None

    return None, 0, 0, None


# ── Composite overlay rendering ─────────────────────────────────────────────


def compose_overlay(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    date_text: str,
    time_text: str,
    speed_value: float,
    distance_m: float,
    max_distance_m: Optional[float] = None,
    alt_value: float = 0.0,
    min_alt: Optional[float] = None,
    max_alt: Optional[float] = None,
    iso_value: Optional[float] = None,
    exposure_value: Optional[float] = None,
    temp_value: Optional[float] = None,
    indicator_values: Optional[dict[str, float]] = None,
    max_speed_kmh: Optional[float] = None,
    power_value: Optional[float] = None,
    atemp_value: Optional[float] = None,
    hr_value: Optional[float] = None,
    cad_value: Optional[float] = None,
    battery_value: Optional[float] = None,
    _bboxes: Optional[dict[str, tuple[int, int, int, int]]] = None,
    chart_data: Optional[dict[str, list[float]]] = None,
    current_position: Optional[float] = None,
    extra_indicators: Optional[dict[str, tuple[float, str, str]]] = None,
    gps_track: Optional[list[tuple[Any, float, float]]] = None,
    target_dt: Optional[datetime] = None,
    start_dt_utc: Optional[datetime] = None,
) -> Image.Image:
    """Compose the complete HUD overlay image from all indicators.

    Each indicator is rendered according to its layout config and blended
    onto a transparent RGBA canvas.

    Args:
        canvas_w, canvas_h: Output image dimensions.
        layout: Full HUD layout dict.
        font_path: Path to TrueType font.
        date_text, time_text: Formatted date/time strings.
        speed_value, distance_m, alt_value: Primary telemetry values.
        indicator_values: Optional per-indicator value overrides (metres for dist).
        _bboxes: Optional dict to populate with indicator bounding boxes.
        chart_data: Optional dict of chart history {key: [values]}.
        current_position: 0.0-1.0 playback position for chart cursors.
        extra_indicators: Optional dict of dynamically discovered indicators
            {key: (value, unit, label)} (e.g. FIT fields).

    Returns:
        RGBA PIL.Image with all indicators composited.
    """
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if _bboxes is None:
        _bboxes = {}

    # Time block
    if "time_block" in layout.get("indicators", {}):
        tb, tbx, tby = render_time_block(canvas_w, canvas_h, layout, font_path, date_text, time_text)
        if tb:
            tb_rotation = layout["indicators"]["time_block"].get("rotation", 0)
            rotated_paste(img, tb, tbx + tb.width // 2, tby + tb.height // 2, tb_rotation)
            if tb_rotation == 90:
                _bboxes["time_block"] = (
                    int(tbx - tb.height // 2),
                    int(tby - tb.width // 2),
                    tb.height,
                    tb.width,
                )
            else:
                _bboxes["time_block"] = (
                    int(tbx - tb.width // 2),
                    int(tby - tb.height // 2),
                    tb.width,
                    tb.height,
                )

    if indicator_values is None:
        indicator_values = {}

    # All indicators to render
    indicator_defs = [
        ("speed_visual", speed_value, "km/h", ""),
        ("speed_text", speed_value, "km/h", ""),
        ("dist_visual", distance_m / 1000.0, "km", ""),
        ("dist_text", distance_m / 1000.0, "km", ""),
        ("alt_visual", alt_value, "m", "Alt"),
        ("alt_text", alt_value, "m", "Alt"),
        ("iso_text", iso_value if iso_value is not None else 0, "ISO", "ISO"),
        ("exposure_text", exposure_value if exposure_value is not None else 0, "", "Exp"),
        ("temp_text", temp_value if temp_value is not None else 0, "C", "Temp"),
        ("power_text", power_value if power_value is not None else 0, "W", "Moc"),
        ("atemp_text", atemp_value if atemp_value is not None else 0, "\u00b0C", "ATemp"),
        ("hr_text", hr_value if hr_value is not None else 0, "BPM", "HR"),
        ("cad_text", cad_value if cad_value is not None else 0, "RPM", "Cad"),
        ("battery_text", battery_value if battery_value is not None else 0, "%", "Bat"),
        ("track_map", 0.0, "", "Mapa"),
    ]

    for key, default_value, unit, default_label in indicator_defs:
        # Skip missing or disabled indicators early
        ind_cfg_orig = layout["indicators"].get(key)
        if ind_cfg_orig is None or (not ind_cfg_orig.get("enabled", True)):
            continue
        if key in indicator_values:
            raw = indicator_values[key]
            if key in ("dist_visual", "dist_text"):
                value = raw / 1000.0
            else:
                value = raw
        else:
            value = float(default_value)

        current_cfg = layout["indicators"][key].copy()

        if key == "dist_visual" and max_distance_m is not None:
            current_cfg["max_val"] = max(current_cfg["min_val"] + 0.001, max_distance_m / 1000.0)

        if key == "speed_visual" and max_speed_kmh is not None:
            rounded = math.ceil(max_speed_kmh / 10.0) * 10
            current_cfg["max_val"] = max(current_cfg.get("min_val", 0) + 0.001, rounded)

        if key in ("alt_visual", "alt_text") and min_alt is not None and max_alt is not None:
            current_cfg["min_val"] = min_alt
            current_cfg["max_val"] = max(min_alt + 1.0, max_alt)

        label = current_cfg.get("label", default_label)

        # Build formatted value
        if key == "iso_text":
            fv = f"{int(value)}"
        elif key == "exposure_text":
            fv = f"1/{int(value)}" if value and int(value) > 0 else ""
        elif key == "temp_text":
            fv = f"{int(value)}\u00b0C"
        elif key == "power_text":
            fv = f"{int(value)}W"
        elif key == "atemp_text":
            fv = f"{int(value)}\u00b0C"
        elif key == "hr_text":
            fv = f"{int(value)} BPM"
        elif key == "cad_text":
            fv = f"{int(value)} RPM"
        elif key == "battery_text":
            fv = f"{int(value)}%"
        else:
            fv = None

        chart_vals = None
        if chart_data and key in chart_data:
            chart_vals = chart_data[key]

        # Determine supersampling factor (global or per-indicator)
        global_ss = layout.get("global", {}).get("antialiasing", 1)
        ss = current_cfg.get("supersample", global_ss)
        res, rx, ry, extra = render_value_indicator(
            canvas_w,
            canvas_h,
            layout,
            font_path,
            key,
            value,
            unit,
            label,
            cfg_override=current_cfg,
            formatted_val=fv,
            max_distance_m=max_distance_m,
            history_data=chart_vals,
            current_position=current_position,
            gps_track=gps_track,
            supersample=ss,
            target_dt=target_dt,
        )

        if res:
            rotation = layout["indicators"][key].get("rotation", 0)
            if layout["indicators"][key].get("form", "text") == "text":
                if rotation == 90:
                    rx = rx + res.height // 2
                else:
                    rx = rx + res.width // 2
            rotated_paste(img, res, rx, ry, rotation)

            if rotation == 90:
                _bboxes[key] = (
                    int(ry - res.height // 2),
                    int(rx - res.width // 2),
                    res.height,
                    res.width,
                )
            elif rotation == 180:
                _bboxes[key] = (
                    int(rx - res.width // 2),
                    int(ry - res.height // 2),
                    res.width,
                    res.height,
                )
            elif rotation == 270:
                _bboxes[key] = (
                    int(ry - res.width // 2),
                    int(rx - res.height // 2),
                    res.height,
                    res.width,
                )
            else:
                _bboxes[key] = (
                    int(rx - res.width // 2),
                    int(ry - res.height // 2),
                    res.width,
                    res.height,
                )

            draw = ImageDraw.Draw(img)
            cfg = current_cfg
            fs = max(10, int(s(cfg["font_size"], canvas_h)))
            font = load_font(font_path, fs)
            outline = max(1, fs // 12)

            if extra and extra.get("show_value") and key != "dist_visual":
                text = extra["value_text"]
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                ox = int(round(cfg.get("text_offset_x", 0.0) * canvas_w))
                oy = int(round(cfg.get("text_offset_y", 0.0) * canvas_h))
                if rotation == 90:
                    text_x = int(rx + res.height + 8 + ox)
                    text_y = int(ry + res.width / 2 - text_h / 2 + oy)
                else:
                    text_x = int(rx + extra["dot_x"] - text_w / 2 + ox)
                    text_y = int(ry + extra["dot_y"] - text_h - 8 + oy)
                draw.text(
                    (text_x, text_y),
                    text,
                    font=font,
                    fill=(255, 255, 255, 255),
                    stroke_width=outline,
                    stroke_fill=(0, 0, 0, 255),
                )

            if extra and extra.get("show_range_labels"):
                left_text = extra.get("left_text", f"{cfg.get('min_val', 0):.0f}")
                right_text = extra.get("right_text", f"{cfg.get('max_val', 100):.0f}")
                rox = int(round(cfg.get("range_label_offset_x", 0.0) * canvas_w))
                roy = int(round(cfg.get("range_label_offset_y", 0.0) * canvas_h))
                rspreadx = int(round(cfg.get("range_label_spread_x", 0.0) * canvas_w))

                left_bbox = draw.textbbox((0, 0), left_text, font=font)
                left_w = left_bbox[2] - left_bbox[0]
                left_h = left_bbox[3] - left_bbox[1]
                if right_text:
                    right_bbox = draw.textbbox((0, 0), right_text, font=font)
                    right_w = right_bbox[2] - right_bbox[0]
                    right_h = right_bbox[3] - right_bbox[1]
                else:
                    right_w = right_h = 0

                if rotation == 90:
                    left_x = int(rx - res.width // 2 + extra["x1"] - left_w - 8 + rox)
                    left_y = int(ry + res.width - left_h / 2 + roy)
                    draw.text(
                        (left_x, left_y),
                        left_text,
                        font=font,
                        fill=(220, 220, 220, 255),
                        stroke_width=outline,
                        stroke_fill=(0, 0, 0, 255),
                    )
                    if right_text:
                        right_x = int(rx - res.width // 2 + extra["x2"] + rox)
                        right_y = int(ry - right_h / 2 + roy - rspreadx)
                        draw.text(
                            (right_x, right_y),
                            right_text,
                            font=font,
                            fill=(220, 220, 220, 255),
                            stroke_width=outline,
                            stroke_fill=(0, 0, 0, 255),
                        )
                else:
                    left_y = int(ry + extra["by"] + 4 + roy)
                    left_x = int(rx - res.width // 2 + extra["x1"] + rox)
                    draw.text(
                        (left_x, left_y),
                        left_text,
                        font=font,
                        fill=(220, 220, 220, 255),
                        stroke_width=outline,
                        stroke_fill=(0, 0, 0, 255),
                    )
                    if right_text:
                        right_x = int(rx - res.width // 2 + extra["x2"] - right_w + rox + rspreadx)
                        draw.text(
                            (right_x, left_y),
                            right_text,
                            font=font,
                            fill=(220, 220, 220, 255),
                            stroke_width=outline,
                            stroke_fill=(0, 0, 0, 255),
                        )

    # ── Extra indicators (dynamically discovered, e.g. FIT fields) ──
    rendered_keys = {k for k, _, _, _ in indicator_defs}
    rendered_keys.add("time_block")  # already rendered above, skip fallback
    if extra_indicators:
        for key, (value, unit, label) in extra_indicators.items():
            if key not in layout["indicators"]:
                continue
            current_cfg = layout["indicators"][key].copy()
            if not current_cfg.get("enabled", True):
                continue
            label = current_cfg.get("label", label)
            fv = f"{value:.1f} {unit}" if unit else f"{value:.1f}"
            chart_vals = chart_data.get(key) if chart_data else None
            res, rx, ry, _extra = render_value_indicator(
                canvas_w, canvas_h, layout, font_path,
                key, value, unit, label,
                cfg_override=current_cfg,
                formatted_val=fv,
                history_data=chart_vals,
                current_position=current_position,
            )
            if res:
                rotation = current_cfg.get("rotation", 0)
                if current_cfg.get("form", "text") == "text":
                    if rotation == 90:
                        rx = rx + res.height // 2
                    else:
                        rx = rx + res.width // 2
                rotated_paste(img, res, rx, ry, rotation)
                _bboxes[key] = (int(rx - res.width // 2), int(ry - res.height // 2), res.width, res.height)
            rendered_keys.add(key)

    # ── FALLBACK: wszystkie pozostałe wskaźniki z layoutu ──────────────
    for key in list(layout.get("indicators", {}).keys()):
        if key in rendered_keys:
            continue
        current_cfg = layout["indicators"][key].copy()
        if not current_cfg.get("enabled", True):
            continue
        val = 0.0
        unit = current_cfg.get("unit", "")
        label = current_cfg.get("label", key)
        if extra_indicators and key in extra_indicators:
            val, unit, label = extra_indicators[key]
        fv = f"{val:.1f} {unit}" if unit else f"{val:.1f}"
        chart_vals = chart_data.get(key) if chart_data else None
        res, rx, ry, _extra = render_value_indicator(
            canvas_w, canvas_h, layout, font_path,
            key, val, unit, label,
            cfg_override=current_cfg,
            formatted_val=fv,
            history_data=chart_vals,
            current_position=current_position,
        )
        if res:
            rotation = current_cfg.get("rotation", 0)
            if current_cfg.get("form", "text") == "text":
                if rotation == 90:
                    rx = rx + res.height // 2
                else:
                    rx = rx + res.width // 2
            rotated_paste(img, res, rx, ry, rotation)
            _bboxes[key] = (int(rx - res.width // 2), int(ry - res.height // 2), res.width, res.height)

    # Custom texts – use resolution-scaled outline
    ct_outline = max(0, int(round(
        int(layout.get("global", {}).get("text_outline", 3)) * min(canvas_w, canvas_h) / 1000
    )))
    for ct_cfg in layout.get("custom_texts", []):
        ct_res, ctx, cty = render_custom_text(canvas_w, canvas_h, font_path, ct_cfg, stroke_width=ct_outline)
        if ct_res:
            ct_rotation = int(ct_cfg.get("rotation", 0))
            rotated_paste(img, ct_res, ctx, cty, ct_rotation)

    return img


# ── Shared chart data builder (used by both preview and render pipeline) ─────


def build_chart_data(
    layout: dict[str, Any],
    get_samples_fn: Callable[[str], tuple[list, list, list]],
    resolve_samples_fn: Callable[[str], list],
) -> dict[str, list[float]]:
    """Build chart history data for all chart-type indicators in a layout.

    This function is shared by the preview (hud_tuner_app.py) and the
    render pipeline (ffmpeg_pipeline.py) to eliminate code duplication
    and ensure identical behaviour in both paths.

    Args:
        layout: HUD layout dict with ``indicators`` key.
        get_samples_fn: ``(source) -> (speed, track, alt)`` triple.
        resolve_samples_fn: ``(field_name) -> list`` for non-speed/alt/dist.

    Returns:
        ``{indicator_key: [values]}`` for every enabled chart indicator.
    """
    chart_data: dict[str, list[float]] = {}
    for ind_key, ind_cfg in layout.get("indicators", {}).items():
        if ind_cfg.get("form") != "chart" or not ind_cfg.get("enabled", True):
            continue
        src = ind_cfg.get("source", "gpmf")
        if "speed" in ind_key:
            spd_s, _, _ = get_samples_fn(src)
            vals = [v for _, v in spd_s] if spd_s else []
        elif "dist" in ind_key:
            _, trk_s, _ = get_samples_fn(src)
            vals = [v for _, v in trk_s] if trk_s else []
        elif "alt" in ind_key:
            _, _, alt_s = get_samples_fn(src)
            vals = [v for _, v in alt_s] if alt_s else []
        elif "power" in ind_key:
            vals = [v for _, v in resolve_samples_fn("power")]
        elif "hr" in ind_key:
            vals = [v for _, v in resolve_samples_fn("hr")]
        elif "cad" in ind_key:
            vals = [v for _, v in resolve_samples_fn("cad")]
        elif "atemp" in ind_key:
            vals = [v for _, v in resolve_samples_fn("atemp")]
        elif "battery" in ind_key:
            vals = [v for _, v in resolve_samples_fn("battery")]
        elif "iso" in ind_key:
            vals = [v for _, v in resolve_samples_fn("iso")]
        elif "exposure" in ind_key:
            vals = [v for _, v in resolve_samples_fn("exposure")]
        elif "temp" in ind_key and "atemp" not in ind_key:
            vals = [v for _, v in resolve_samples_fn("temperature")]
        else:
            # Dla kluczy typu fit_{field_name}_text — wyciągnij field_name
            # i rozwiąż przez resolve_samples_fn
            if ind_key.startswith("fit_") and ind_key.endswith("_text"):
                field_name = ind_key[4:-5]
                vals = [v for _, v in resolve_samples_fn(field_name)]
            else:
                vals = []
        if vals and len(vals) >= 2:
            chart_data[ind_key] = vals
    return chart_data


def render_preview(
    src_img: Image.Image,
    layout: dict[str, Any],
    font_path: str,
    date_text: str,
    time_text: str,
    speed_value: float,
    distance_m: float,
    max_distance_m: Optional[float] = None,
    alt_value: float = 0.0,
    min_alt: Optional[float] = None,
    max_alt: Optional[float] = None,
    iso_value: Optional[float] = None,
    exposure_value: Optional[float] = None,
    temp_value: Optional[float] = None,
    indicator_values: Optional[dict[str, float]] = None,
    max_speed_kmh: Optional[float] = None,
    power_value: Optional[float] = None,
    atemp_value: Optional[float] = None,
    hr_value: Optional[float] = None,
    cad_value: Optional[float] = None,
    battery_value: Optional[float] = None,
    _bboxes: Optional[dict[str, tuple[int, int, int, int]]] = None,
    chart_data: Optional[dict[str, list[float]]] = None,
    current_position: Optional[float] = None,
    extra_indicators: Optional[dict[str, tuple[float, str, str]]] = None,
    gps_track: Optional[list[tuple[Any, float, float]]] = None,
    target_dt: Optional[datetime] = None,
    start_dt_utc: Optional[datetime] = None,
) -> Image.Image:
    """Render a preview image: source frame with HUD overlay composited on top."""
    # Avoid a full-resolution copy if the image is already RGBA
    img = src_img if src_img.mode == "RGBA" else src_img.convert("RGBA")
    img = img.copy()
    w, h = img.size
    if _bboxes is None:
        _bboxes = {}
    overlay = compose_overlay(
        w,
        h,
        layout,
        font_path,
        date_text,
        time_text,
        speed_value,
        distance_m,
        max_distance_m,
        alt_value,
        min_alt,
        max_alt,
        iso_value,
        exposure_value,
        temp_value,
        indicator_values=indicator_values,
        max_speed_kmh=max_speed_kmh,
        power_value=power_value,
        atemp_value=atemp_value,
        hr_value=hr_value,
        cad_value=cad_value,
        battery_value=battery_value,
        _bboxes=_bboxes,
        chart_data=chart_data,
        current_position=current_position,
        extra_indicators=extra_indicators,
        gps_track=gps_track,
        target_dt=target_dt,
        start_dt_utc=start_dt_utc,
    )
    img.alpha_composite(overlay)
    return img
