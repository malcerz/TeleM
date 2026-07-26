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

    chart_img = generate_history_chart(
        chart_vals, chart_w, chart_h,
        line_color=line_clr,
        line_thickness=max(1, int(float(cfg.get("thickness", 1)))),
        fill_alpha=chart_fill_alpha, fill_color=chart_fill_color,
        current_index=ci, cursor_color=(255, 255, 255),
        show_axes=True, grid_color=grid_rgba,
        time_labels=time_labels, supersample=1,
    )

    margin_top = fs + 8 if label else 0
    final_h = chart_h + margin_top + 4
    final_img = Image.new("RGBA", (chart_w + 8, final_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(final_img)

    if label:
        draw.text(
            (4, 0), label, font=font,
            fill=(210, 210, 210, 255),
            stroke_width=outline, stroke_fill=(0, 0, 0, 255),
        )
    final_img.paste(chart_img, (4, margin_top), chart_img)

    v_str = formatted_val if formatted_val else f"{value:.1f} {unit}"
    vw = draw.textbbox((0, 0), v_str, font=font)[2] - 0
    draw.text(
        (chart_w - vw, 0), v_str, font=font,
        fill=(255, 255, 255, 255),
        stroke_width=outline, stroke_fill=(0, 0, 0, 255),
    )
    return final_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
