"""Chart-form indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import math
import time
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.chart_utils import generate_history_chart, get_history_chart_background
from src.indicators.helpers import parse_hex_color, s
from src.indicators.registry import get_chart_color, HARDCODED_KEYS
from src.indicators.profiling import get_overlay_profiler


_FINAL_STATIC_CHART_CACHE = {}
_FINAL_STATIC_CHART_KEYS = frozenset(("fit_cadence_text", "fit_heart_rate_text"))


def _draw_post_paste_cursor(
    image, points, current_index, plot_y1, plot_y2, calc_thickness,
    cursor_color, line_color, offset_x, offset_y, chart_width, chart_height,
):
    """Reproduce the RGBA left by legacy ``paste(chart, mask=chart)``."""
    if current_index is None or not points or not (0 <= current_index < len(points)):
        return
    cursor_x, py = points[current_index]
    cursor_x += offset_x
    py += offset_y
    alpha = 200
    post_rgb = tuple((channel * alpha + 127) // 255 for channel in cursor_color)
    post_alpha = (alpha * alpha + 127) // 255
    draw = ImageDraw.Draw(image)
    draw.line(
        (cursor_x, plot_y1 + offset_y, cursor_x, plot_y2 + offset_y),
        fill=(*post_rgb, post_alpha), width=max(2, calc_thickness),
    )
    dot_r = max(3, calc_thickness + 1)
    # Render the opaque dot in a tiny tile so clipping remains identical to
    # drawing on the old chart-sized image before it was pasted into the widget.
    left = math.floor(cursor_x - dot_r)
    top = math.floor(py - dot_r)
    right = math.ceil(cursor_x + dot_r) + 1
    bottom = math.ceil(py + dot_r) + 1
    tile = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.ellipse(
        (cursor_x - dot_r - left, py - dot_r - top,
         cursor_x + dot_r - left, py + dot_r - top),
        fill=(*cursor_color, 255), outline=(*line_color, 255),
    )
    clip_left, clip_top = offset_x, offset_y
    clip_right, clip_bottom = offset_x + chart_width, offset_y + chart_height
    dst_left, dst_top = max(left, clip_left), max(top, clip_top)
    dst_right, dst_bottom = min(right, clip_right), min(bottom, clip_bottom)
    if dst_right > dst_left and dst_bottom > dst_top:
        clipped = tile.crop((
            dst_left - left, dst_top - top, dst_right - left, dst_bottom - top,
        ))
        image.paste(clipped, (dst_left, dst_top), clipped)


def _render_chart_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    history_data=None, current_position=None, formatted_val=None,
):
    """Render a chart-form indicator."""
    profiler = get_overlay_profiler()
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

    graph_kwargs = dict(
        line_color=line_clr, line_thickness=max(1, line_width),
        fill_alpha=chart_fill_alpha, fill_color=chart_fill_color,
        show_axes=True, grid_color=grid_rgba, time_labels=time_labels,
        supersample=1, custom_min_val=custom_min, custom_max_val=custom_max,
        label_count=label_count, label_units=label_units, unit=unit,
        show_average=show_average, label_font_size=label_fs_px,
        font_path=font_path,
    )
    optimized_static = key in _FINAL_STATIC_CHART_KEYS
    graph_started = time.perf_counter()
    if optimized_static:
        bg_img, points, plot_y1, plot_y2, calc_thickness, bg_key = (
            get_history_chart_background(chart_vals, chart_w, chart_h, **graph_kwargs)
        )
        chart_img = None
    else:
        chart_img = generate_history_chart(
            chart_vals, chart_w, chart_h, current_index=ci,
            cursor_color=(255, 255, 255), **graph_kwargs,
        )
    profiler.record(
        "graph.history_chart_total",
        (time.perf_counter() - graph_started) * 1000.0,
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

    assembly_started = time.perf_counter()
    if optimized_static:
        final_key = (
            "final_static_chart", bg_key, hdr_key, chart_w + 8, final_h,
            margin_top,
        )
        final_static = _FINAL_STATIC_CHART_CACHE.get(final_key)
        if final_static is None:
            static_started = time.perf_counter()
            final_static = hdr_img.copy()
            final_static.paste(bg_img, (4, margin_top), bg_img)
            if len(_FINAL_STATIC_CHART_CACHE) > 50:
                _FINAL_STATIC_CHART_CACHE.clear()
            _FINAL_STATIC_CHART_CACHE[final_key] = final_static
            profiler.record(
                "graph.final_static_build",
                (time.perf_counter() - static_started) * 1000.0,
            )
        final_img = final_static.copy()
        cursor_started = time.perf_counter()
        _draw_post_paste_cursor(
            final_img, points, ci, plot_y1, plot_y2, calc_thickness,
            (255, 255, 255), line_clr, 4, margin_top, chart_w, chart_h,
        )
        profiler.record(
            "graph.current_cursor",
            (time.perf_counter() - cursor_started) * 1000.0,
        )
    else:
        final_img = hdr_img.copy()
        final_img.paste(chart_img, (4, margin_top), chart_img)
    profiler.record(
        "graph.background_and_chart_composite",
        (time.perf_counter() - assembly_started) * 1000.0,
    )
    draw = ImageDraw.Draw(final_img)

    v_str = formatted_val if formatted_val is not None else f"{value:.1f} {unit}"
    if v_str:
        labels_started = time.perf_counter()
        vw = draw.textbbox((0, 0), v_str, font=font)[2] - 0
        draw.text(
            (chart_w - vw + tox, toy), v_str, font=font,
            fill=text_color,
            stroke_width=outline, stroke_fill=(0, 0, 0, 255),
        )
        profiler.record(
            "graph.dynamic_labels",
            (time.perf_counter() - labels_started) * 1000.0,
        )
    return final_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
