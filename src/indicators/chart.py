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
from src.indicators.helpers import (
    _STATIC_CACHE,
    _static_cache_key,
    compose_5q_optimized,
    parse_hex_color,
    s,
)
from src.indicators.registry import get_chart_color, HARDCODED_KEYS
from src.indicators.profiling import get_overlay_profiler


_FINAL_STATIC_CHART_CACHE = {}
_FINAL_STATIC_CHART_KEYS = frozenset(("fit_cadence_text", "fit_heart_rate_text"))


class ChartSplit:
    """ETAP 5K — the split (static + dynamic) representation of a chart.

    Instead of a full 1160x511 RGBA chart built per frame, the chart is split
    into a *static* layer (uploaded to the GPU once per cache invalidation) and
    two small *dynamic* layers (cursor + current value) uploaded per frame.

    ``cursor_local`` / ``value_local`` are the tile top-lefts in the chart
    image coordinate space (0..chart_w+8, 0..final_h) — the exporter adds the
    chart's HUD bbox top-left to get the GPU blend destination.
    """

    __slots__ = (
        "static", "cursor_tile", "cursor_local", "value_tile", "value_local",
        "width", "height",
    )

    def __init__(self, static, cursor_tile, cursor_local, value_tile, value_local):
        self.static = static
        self.cursor_tile = cursor_tile
        self.cursor_local = cursor_local
        self.value_tile = value_tile
        self.value_local = value_local
        self.width, self.height = static.size

    @property
    def size(self):
        return (self.width, self.height)


def _resolve_cursor_coords(points, current_index):
    """Resolve cursor (x, y) coordinates from either a (cursor_x, py) tuple or an index."""
    if current_index is None or not points:
        return None
    if isinstance(current_index, (tuple, list)) and len(current_index) == 2:
        return float(current_index[0]), float(current_index[1])
    if isinstance(current_index, int) and 0 <= current_index < len(points):
        return points[current_index]
    return None


def _cursor_tile_bbox(
    points, current_index, plot_y1, plot_y2, calc_thickness,
    offset_x, offset_y, chart_width, chart_height,
):
    """Clipped cursor bbox (line + dot) in chart-image coordinates."""
    coords = _resolve_cursor_coords(points, current_index)
    if coords is None:
        return None
    cursor_x, py = coords
    cursor_x += offset_x
    py += offset_y
    dot_r = max(3, calc_thickness + 1)
    clip_left, clip_top = offset_x, offset_y
    clip_right = offset_x + chart_width
    clip_bottom = offset_y + chart_height
    left = math.floor(cursor_x - dot_r)
    top = min(plot_y1 + offset_y, math.floor(py - dot_r))
    right = math.ceil(cursor_x + dot_r) + 1
    bottom = max(plot_y2 + offset_y, math.ceil(py + dot_r) + 1)
    dst_left, dst_top = max(left, clip_left), max(top, clip_top)
    dst_right, dst_bottom = min(right, clip_right), min(bottom, clip_bottom)
    if dst_right <= dst_left or dst_bottom <= dst_top:
        return None
    return (dst_left, dst_top, dst_right, dst_bottom)


def _draw_post_paste_cursor(
    image, points, current_index, plot_y1, plot_y2, calc_thickness,
    cursor_color, line_color, offset_x, offset_y, chart_width, chart_height,
):
    """Reproduce the RGBA left by legacy ``paste(chart, mask=chart)``.

    NOTE: the line is drawn DIRECTLY on the image (Pillow's draw.line blend over
    the existing pixels) and only the opaque dot is pasted via an RGBA tile.
    This exact ordering/operation is what 5D/5J validated; do not replace the
    line draw with a tile paste (Pillow's paste with an RGBA mask pre-multiplies
    alpha and would change the output).
    """
    coords = _resolve_cursor_coords(points, current_index)
    if coords is None:
        return
    cursor_x, py = coords
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


def _clip_tile(tile, local, clip_w, clip_h):
    """Clip a dynamic tile to the chart image bounds ``[0, clip_w) x [0, clip_h)``.

    The value text stroke can extend above the chart top (negative y) or past
    the right edge; the legacy full-image render clips those pixels away.  The
    GPU blend (and the CPU reconstruction) must reproduce that clip, so the
    tile is cropped here and its local offset is re-anchored at the chart
    origin (never negative).
    """
    if tile is None:
        return None, (0, 0)
    lx, ly = local
    x0, y0 = max(0, lx), max(0, ly)
    x1, y1 = min(clip_w, lx + tile.width), min(clip_h, ly + tile.height)
    if x1 <= x0 or y1 <= y0:
        return None, (0, 0)
    cropped = tile.crop((x0 - lx, y0 - ly, x1 - lx, y1 - ly))
    return cropped, (x0, y0)


def _render_value_text_tile(
    v_str, font, text_color, outline, chart_w, tox, toy,
):
    """Render the dynamic current-value text to a tight transparent tile.

    Returns ``(tile, local_left, local_top)``.  The tile is sized from the
    stroke-inclusive text bbox; the draw origin is preserved so the glyphs land
    at the exact chart-image position the full-image render would use.
    """
    if not v_str:
        return None, 0, 0
    if compose_5q_optimized():
        # ETAP 5Q: value-keyed tile cache (byte-exact; the tile and the
        # layout metrics are identical for the same value string).
        key = _static_cache_key(
            "value_text_tile", v_str,
            str(getattr(font, "path", "")), int(getattr(font, "size", 0)),
            text_color, outline,
        )
        cached = _STATIC_CACHE.get(key)
        if cached is not None:
            tile, vw, sl, st = cached
            px = chart_w - vw + tox
            py = toy
            return tile, px + sl, py + st
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        vw = probe.textbbox((0, 0), v_str, font=font)[2]
        sl, st, sr, sb = probe.textbbox((0, 0), v_str, font=font, stroke_width=outline)
        tile = Image.new("RGBA", (max(1, sr - sl), max(1, sb - st)), (0, 0, 0, 0))
        tdraw = ImageDraw.Draw(tile)
        tdraw.text(
            (-sl, -st), v_str, font=font, fill=text_color,
            stroke_width=outline, stroke_fill=(0, 0, 0, 255),
        )
        _STATIC_CACHE[key] = (tile, vw, sl, st)
        px = chart_w - vw + tox
        py = toy
        return tile, px + sl, py + st
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    vw = probe.textbbox((0, 0), v_str, font=font)[2]
    px = chart_w - vw + tox
    py = toy
    sl, st, sr, sb = probe.textbbox((0, 0), v_str, font=font, stroke_width=outline)
    tile = Image.new("RGBA", (max(1, sr - sl), max(1, sb - st)), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tile)
    # Draw at (-sl, -st) so tile pixel (i, j) reproduces the CPU pixel at the
    # same absolute layout position (the stroke bbox is relative to the text
    # origin; drawing at (sl, st) would double-shift the glyphs).
    tdraw.text(
        (-sl, -st), v_str, font=font, fill=text_color,
        stroke_width=outline, stroke_fill=(0, 0, 0, 255),
    )
    return tile, px + sl, py + st


def _render_chart_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    history_data=None, current_position=None, formatted_val=None,
    split_mode=False, target_dt=None,
):
    """Render a chart-form indicator."""
    profiler = get_overlay_profiler()
    time_labels = None
    chart_vals = None
    timestamps = None
    if isinstance(history_data, dict):
        chart_vals = history_data.get("values", [])
        time_labels = history_data.get("time_labels")
        timestamps = history_data.get("timestamps")
    elif isinstance(history_data, list):
        chart_vals = history_data
        timestamps = getattr(history_data, "timestamps", None)

    if not chart_vals or len(chart_vals) < 2:
        chart_vals = [value, value]

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
    bg_img, points, plot_y1, plot_y2, calc_thickness, bg_key = (
        get_history_chart_background(chart_vals, chart_w, chart_h, **graph_kwargs)
    )

    ci = None
    chart_start_dt = getattr(history_data, "chart_start_dt", None)
    chart_end_dt = getattr(history_data, "chart_end_dt", None)
    t_start = chart_start_dt or (timestamps[0] if timestamps else None)
    t_end = chart_end_dt or (timestamps[-1] if timestamps else None)

    pos = None
    align_start = t_start
    align_end = t_end
    if timestamps and len(timestamps) >= 1 and target_dt is not None and t_start is not None and t_end is not None:
        sample_tz = timestamps[0].tzinfo
        aligned_target = target_dt
        if sample_tz is None and target_dt.tzinfo is not None:
            aligned_target = target_dt.replace(tzinfo=None)
        elif sample_tz is not None and target_dt.tzinfo is None:
            from datetime import timezone
            aligned_target = target_dt.replace(tzinfo=timezone.utc)

        if sample_tz is None:
            if align_start.tzinfo is not None:
                align_start = align_start.replace(tzinfo=None)
            if align_end.tzinfo is not None:
                align_end = align_end.replace(tzinfo=None)
        else:
            if align_start.tzinfo is None:
                align_start = align_start.replace(tzinfo=timezone.utc)
            if align_end.tzinfo is None:
                align_end = align_end.replace(tzinfo=timezone.utc)

        if align_end > align_start:
            pos = (aligned_target - align_start).total_seconds() / (align_end - align_start).total_seconds()
            pos = max(0.0, min(1.0, pos))
    elif current_position is not None:
        pos = max(0.0, min(1.0, current_position))

    if pos is not None and points:
        if (
            timestamps
            and len(timestamps) == len(points)
            and align_start is not None
            and align_end is not None
            and align_end > align_start
        ):
            norm_0 = max(0.0, min(1.0, (timestamps[0] - align_start).total_seconds() / (align_end - align_start).total_seconds()))
            norm_last = max(0.0, min(1.0, (timestamps[-1] - align_start).total_seconds() / (align_end - align_start).total_seconds()))
            if norm_last > norm_0:
                plot_w_span = (points[-1][0] - points[0][0]) / (norm_last - norm_0)
                plot_x1_base = points[0][0] - norm_0 * plot_w_span
                cursor_x = plot_x1_base + pos * plot_w_span
            else:
                cursor_x = points[0][0]
        else:
            cursor_x = points[0][0] + pos * (points[-1][0] - points[0][0])

        if timestamps and len(timestamps) == len(points) and target_dt is not None:
            from bisect import bisect_right
            idx = bisect_right(timestamps, aligned_target) - 1
            if idx < 0:
                py = points[0][1]
            elif idx >= len(points) - 1:
                py = points[-1][1]
            else:
                dt0, dt1 = timestamps[idx], timestamps[idx + 1]
                if sample_tz is None:
                    if dt0.tzinfo is not None:
                        dt0 = dt0.replace(tzinfo=None)
                    if dt1.tzinfo is not None:
                        dt1 = dt1.replace(tzinfo=None)
                else:
                    if dt0.tzinfo is None:
                        dt0 = dt0.replace(tzinfo=timezone.utc)
                    if dt1.tzinfo is None:
                        dt1 = dt1.replace(tzinfo=timezone.utc)
                dt_span = (dt1 - dt0).total_seconds()
                if dt_span > 0:
                    frac = max(0.0, min(1.0, (aligned_target - dt0).total_seconds() / dt_span))
                    py = points[idx][1] + frac * (points[idx + 1][1] - points[idx][1])
                else:
                    py = points[idx][1]
        else:
            idx = int(round(pos * (len(points) - 1)))
            idx = max(0, min(len(points) - 1, idx))
            py = points[idx][1]

        ci = (cursor_x, py)

    if not optimized_static:
        chart_img = generate_history_chart(
            chart_vals, chart_w, chart_h, current_index=ci,
            cursor_color=(255, 255, 255), **graph_kwargs,
        )
    else:
        chart_img = None
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
    v_str = formatted_val if formatted_val is not None else f"{value:.1f} {unit}"

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
        v_str = formatted_val if formatted_val is not None else f"{value:.1f} {unit}"
        if split_mode:
            # ETAP 5K: hand the exporter a static layer + two small dynamic
            # tiles instead of a full per-frame chart image.  No final_static
            # copy, no full tobytes, no full 1160x511 texture upload.
            #
            # The dynamic tiles are pre-composited over the static on the CPU
            # (cursor line/dot drawn onto a static crop, value text onto the
            # transparent header) and the GPU *replaces* their region in the
            # HUD canvas after blending the static — Pillow's draw/paste blends
            # are not identical to the GPU's straight-alpha "over", so a
            # separate transparent overlay could never be pixel-exact.  These
            # tiles ARE the exact final-chart pixels of their regions.
            cursor_started = time.perf_counter()
            cursor_bbox = _cursor_tile_bbox(
                points, ci, plot_y1, plot_y2, calc_thickness,
                4, margin_top, chart_w, chart_h,
            )
            if cursor_bbox is None:
                cursor_tile = None
                cursor_local = (0, 0)
            else:
                clx, cly, crx, cry = cursor_bbox
                cursor_tile = final_static.crop((clx, cly, crx, cry)).copy()
                _draw_post_paste_cursor(
                    cursor_tile, points, ci, plot_y1, plot_y2, calc_thickness,
                    (255, 255, 255), line_clr, 4 - clx, margin_top - cly,
                    chart_w, chart_h,
                )
                cursor_local = (clx, cly)
            profiler.record(
                "graph.current_cursor",
                (time.perf_counter() - cursor_started) * 1000.0,
            )
            labels_started = time.perf_counter()
            value_tile, v_left, v_top = _render_value_text_tile(
                v_str, font, text_color, outline, chart_w, tox, toy,
            )
            profiler.record(
                "graph.dynamic_labels",
                (time.perf_counter() - labels_started) * 1000.0,
            )
            # Clip dynamic tiles to the chart image bounds so the GPU never
            # writes outside the chart bbox (the legacy render clips the value
            # stroke above the chart top).
            cursor_tile, cursor_local = _clip_tile(
                cursor_tile, cursor_local, chart_w + 8, final_h)
            value_tile, (v_left, v_top) = _clip_tile(
                value_tile, (v_left, v_top), chart_w + 8, final_h)
            profiler.record(
                "graph.background_and_chart_composite",
                (time.perf_counter() - assembly_started) * 1000.0,
            )
            split = ChartSplit(
                final_static,
                cursor_tile, cursor_local,
                value_tile, (v_left, v_top),
            )
            return split, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
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
