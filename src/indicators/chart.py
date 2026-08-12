"""Chart-form indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.chart_utils import generate_history_chart
from src.indicators.helpers import parse_hex_color, s
from src.indicators.registry import get_chart_color, HARDCODED_KEYS


def _render_chart_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    history_data=None, current_position=None, formatted_val=None,
):
    """Render a chart-form indicator."""
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
    else:
        line_clr = get_chart_color(key)

    chart_fill_alpha = int(cfg.get("fill_alpha", 40))
    chart_fill_color = parse_hex_color(cfg.get("fill_color", ""))

    # Grid
    show_grid = bool(cfg.get("show_grid", True))
    grid_rgba = None
    if show_grid:
        grid_color_hex = cfg.get("grid_color", "#444444")
        gc = parse_hex_color(grid_color_hex)
        if gc:
            grid_rgba = (gc[0], gc[1], gc[2], 60)

    line_width = int(cfg.get("line_width", cfg.get("thickness", 2)))
    custom_min = float(cfg["min_val"]) if "min_val" in cfg else None
    custom_max = float(cfg["max_val"]) if "max_val" in cfg else None
    label_count = int(cfg.get("label_count", 2))
    label_units = bool(cfg.get("label_units", False))
    show_average = bool(cfg.get("show_average", False))

    # label_font_size (Właściwości) → pixel size, clamped to fit the chart
    lfs = cfg.get("label_font_size")
    if lfs:
        label_fs_px = max(7, int(s(float(lfs), min_dim)))
        label_fs_px = min(label_fs_px, max(8, chart_h // 2))
    else:
        label_fs_px = 0

    chart_img = generate_history_chart(
        chart_vals, chart_w, chart_h,
        line_color=line_clr,
        line_thickness=max(1, line_width),
        fill_alpha=chart_fill_alpha, fill_color=chart_fill_color,
        current_index=ci, cursor_color=(255, 255, 255),
        show_axes=True, grid_color=grid_rgba,
        time_labels=time_labels, supersample=1,
        custom_min_val=custom_min, custom_max_val=custom_max,
        label_count=label_count, label_units=label_units, unit=unit,
        show_average=show_average,
        label_font_size=label_fs_px, font_path=font_path,
    )

    margin_top = fs + 8 if label else 0
    final_h = chart_h + margin_top + 4

    text_color_rgb = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
    text_color = (text_color_rgb[0], text_color_rgb[1], text_color_rgb[2], 255)

    tox = int(round(cfg.get("text_offset_x", 0.0) * chart_w))
    toy = int(round(cfg.get("text_offset_y", 0.0) * chart_h))

    from src.indicators.helpers import _STATIC_CACHE, _static_cache_key
    hdr_key = _static_cache_key("chart_hdr", chart_w + 8, final_h, label, font_path, fs, outline, text_color, tox, toy)
    hdr_img = _STATIC_CACHE.get(hdr_key)
    if hdr_img is None:
        hdr_img = Image.new("RGBA", (chart_w + 8, final_h), (0, 0, 0, 0))
        if label:
            d_hdr = ImageDraw.Draw(hdr_img)
            d_hdr.text(
                (4 + tox, toy), label, font=font,
                fill=text_color,
                stroke_width=outline, stroke_fill=(0, 0, 0, 255),
            )
        _STATIC_CACHE[hdr_key] = hdr_img

    final_img = hdr_img.copy()
    final_img.paste(chart_img, (4, margin_top), chart_img)
    draw = ImageDraw.Draw(final_img)

    v_str = formatted_val if formatted_val is not None else f"{value:.1f} {unit}"
    if v_str:
        vw = draw.textbbox((0, 0), v_str, font=font)[2] - 0
        draw.text(
            (chart_w - vw + tox, toy), v_str, font=font,
            fill=text_color,
            stroke_width=outline, stroke_fill=(0, 0, 0, 255),
        )
    return final_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
