"""Chart generation utilities — standalone line chart rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import time
import threading
import math
from typing import Optional
from bisect import bisect_right

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import load_font, load_font_cache_small
from src.indicators.profiling import get_overlay_profiler


from datetime import timezone


_CHART_BG_CACHE: dict[tuple, tuple[Image.Image, list[tuple[float, float]], float, float]] = {}
_CHART_PREFIX_GEOMETRY_CACHE: dict[tuple, tuple] = {}
_CHART_STATIC_ALPHA_BBOX_CACHE: dict[tuple, tuple[int, int, int, int] | None] = {}
_CHART_AXIS_CACHE: dict[tuple, tuple[Image.Image, float, float, float, float]] = {}
_AVERAGE_LAYER_CACHE_LOCAL = threading.local()
_AVERAGE_LAYER_CACHE_ENABLED = True


def set_average_layer_cache_enabled(enabled: bool) -> None:
    global _AVERAGE_LAYER_CACHE_ENABLED
    _AVERAGE_LAYER_CACHE_ENABLED = bool(enabled)


def _average_layer_cache_state() -> dict:
    state = getattr(_AVERAGE_LAYER_CACHE_LOCAL, "state", None)
    if state is None:
        state = {"layers": {}, "hits": 0, "misses": 0}
        _AVERAGE_LAYER_CACHE_LOCAL.state = state
    return state


def reset_average_layer_cache_stats() -> None:
    """Reset worker-local average-layer cache and counters for A/B tests."""
    _AVERAGE_LAYER_CACHE_LOCAL.state = {"layers": {}, "hits": 0, "misses": 0}


def get_average_layer_cache_stats() -> dict[str, int | float]:
    state = _average_layer_cache_state()
    hits = int(state["hits"])
    misses = int(state["misses"])
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hit_percent": (100.0 * hits / total) if total else 0.0,
    }


def _history_cache_token(history_values) -> object:
    return getattr(history_values, "_chart_cache_token", id(history_values))


def get_chart_static_alpha_bbox(cache_key):
    """Return cached alpha bounds of immutable chart axes/background geometry."""
    if cache_key in _CHART_STATIC_ALPHA_BBOX_CACHE:
        return _CHART_STATIC_ALPHA_BBOX_CACHE[cache_key]
    geometry = _CHART_PREFIX_GEOMETRY_CACHE.get(cache_key)
    if geometry is None:
        cached = _CHART_BG_CACHE.get(cache_key)
        source = cached[0] if cached is not None else None
    else:
        source = geometry[0]
    bbox = source.getchannel("A").getbbox() if source is not None else None
    if len(_CHART_STATIC_ALPHA_BBOX_CACHE) >= 64:
        _CHART_STATIC_ALPHA_BBOX_CACHE.clear()
    _CHART_STATIC_ALPHA_BBOX_CACHE[cache_key] = bbox
    return bbox


def _get_cached_average_layer(
    history_values,
    visible_index: int,
    plot_x1: float,
    plot_x2: float,
    visible_x2: float,
    plot_y1: float,
    plot_y2: float,
    data_min: float,
    data_max: float,
    visible_sum: float,
    visible_numeric_count: int,
    width: int,
    height: int,
    supersample: int,
):
    """Return an exact ImageDraw-compatible average-line mask and placement."""
    state = _average_layer_cache_state()
    avg_val = visible_sum / visible_numeric_count if visible_numeric_count else None
    if avg_val is None or not (data_min <= avg_val <= data_max):
        return None, (0, 0), avg_val

    safe_max = data_max if data_max > data_min else data_min + 1.0
    avg_y = plot_y2 - ((avg_val - data_min) / (safe_max - data_min)) * (plot_y2 - plot_y1)
    step = 6 * max(1, int(supersample))
    key = (
        "average_layer", _history_cache_token(history_values), int(visible_index),
        int(width), int(height), int(supersample),
        float(plot_x1), float(plot_x2), float(visible_x2), float(plot_y1), float(plot_y2),
        float(data_min), float(data_max),
    )
    cached = state["layers"].get(key)
    if cached is not None:
        state["hits"] += 1
        mask, origin, cached_avg_y = cached
        if mask is None:
            return None, (avg_val, cached_avg_y)
        return (mask, origin), (avg_val, cached_avg_y)

    state["misses"] += 1
    mask = Image.new("L", (int(width), int(height)), 0)
    draw = ImageDraw.Draw(mask)
    visible_x2 = max(plot_x1, min(plot_x2, visible_x2))
    for x in range(int(plot_x1), int(visible_x2), step):
        draw.line(
            (x, avg_y, min(x + 3 * max(1, int(supersample)), visible_x2), avg_y),
            fill=255, width=max(1, int(supersample)),
        )
    bbox = mask.getbbox()
    if bbox is None:
        cached = (None, (0, 0), avg_y)
        state["layers"][key] = cached
        return None, (avg_val, avg_y)
    origin = (bbox[0], bbox[1])
    mask = mask.crop(bbox)
    cached = (mask, origin, avg_y)
    # The reference material has about 168 HR visible-index states.  Keep a
    # small bounded cache large enough to retain that complete state set while
    # still preventing unbounded growth for arbitrary layouts/histories.
    if len(state["layers"]) >= 256:
        state["layers"].clear()
    state["layers"][key] = cached
    return (mask, origin), (avg_val, avg_y)


def _split_chart_segments(
    points: list[tuple[float, float]],
    timestamps=None,
    values=None,
) -> list[list[tuple[float, float]]]:
    """Split a chart polyline at missing values and telemetry time gaps.

    A chart must not invent a connection across a missing sample or a long
    pause in the source stream.  The returned points remain unchanged; this
    helper only defines which consecutive points may be drawn together.
    """
    if not points:
        return []
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = [points[0]]
    deltas = []
    if timestamps and len(timestamps) == len(points):
        for left, right in zip(timestamps, timestamps[1:]):
            try:
                delta = (right - left).total_seconds()
            except AttributeError:
                delta = 0.0
            if delta > 0:
                deltas.append(delta)
    nominal = sorted(deltas)[len(deltas) // 2] if deltas else 0.0
    gap_limit = max(5.0, nominal * 3.0) if nominal > 0 else None

    for idx, point in enumerate(points[1:], 1):
        missing = values is not None and (
            values[idx - 1] is None or values[idx] is None
        )
        time_gap = False
        if gap_limit is not None and timestamps and len(timestamps) == len(points):
            try:
                time_gap = (timestamps[idx] - timestamps[idx - 1]).total_seconds() > gap_limit
            except AttributeError:
                time_gap = False
        if missing or time_gap:
            if current:
                segments.append(current)
            current = [point]
        else:
            current.append(point)
    if current:
        segments.append(current)
    return segments


def _chart_segment_ranges(timestamps, values) -> list[tuple[int, int]]:
    """Return immutable ``[start, end)`` ranges using the chart gap rules."""
    if not values:
        return []
    marker_points = [(float(index), 0.0) for index in range(len(values))]
    segments = _split_chart_segments(marker_points, timestamps, values)
    return [
        (int(segment[0][0]), int(segment[-1][0]) + 1)
        for segment in segments if segment
    ]


_NICE_TIME_STEPS = [
    1, 2, 5, 10, 15, 30,
    60, 120, 300, 600, 900, 1800,
    3600, 7200, 14400, 21600, 43200, 86400,
]


def _choose_nice_time_step(duration_s: float, target_count: int = 5) -> float:
    duration_s = max(1.0, float(duration_s))
    best_step = _NICE_TIME_STEPS[0]
    best_score = float("inf")
    for step in _NICE_TIME_STEPS:
        count = int(duration_s // step) + 1
        score = abs(count - target_count)
        if count < 2:
            score += 100
        elif count > 9:
            score += (count - 9) * 2
        if score < best_score:
            best_score = score
            best_step = step
    return float(best_step)


def generate_nice_time_ticks(duration_s: float, target_count: int = 5) -> list[tuple[float, str]]:
    """Generate nice time ticks for a given duration.

    Returns a list of (norm_x, label_str) tuples where norm_x is in [0.0, 1.0].
    Formatting:
    - duration < 1 hour: MM:SS (e.g. 00:00, 02:00)
    - duration >= 1 hour: H:MM (e.g. 0:00, 0:30, 1:00)
    """
    duration_s = max(1.0, float(duration_s))

    best_step = _choose_nice_time_step(duration_s, target_count)

    ticks: list[tuple[float, str]] = []
    tick_sec = 0
    is_hours = duration_s >= 3600.0

    while tick_sec <= duration_s:
        norm_x = tick_sec / duration_s
        if is_hours:
            h = int(tick_sec // 3600)
            m = int((tick_sec % 3600) // 60)
            lbl = f"{h}:{m:02d}"
        else:
            m = int(tick_sec // 60)
            s = int(tick_sec % 60)
            lbl = f"{m:02d}:{s:02d}"
        ticks.append((norm_x, lbl))
        tick_sec += best_step

    return ticks


def generate_nice_relative_time_ticks(
    duration_s: float, target_count: int = 5,
) -> list[tuple[float, str]]:
    """Generate time-accurate negative labels for a moving chart window."""
    duration_s = max(0.0, float(duration_s))
    if duration_s <= 0.0:
        return [(0.0, "0 s")]
    step = _choose_nice_time_step(duration_s, target_count)

    def fmt(seconds: float) -> str:
        rounded = round(seconds)
        if abs(seconds - rounded) < 0.05:
            return str(int(rounded))
        return f"{seconds:.1f}".rstrip("0").rstrip(".")

    ticks: list[tuple[float, str]] = []
    tick_sec = 0.0
    while tick_sec < duration_s:
        remaining = duration_s - tick_sec
        ticks.append((tick_sec / duration_s, f"-{fmt(remaining)} s"))
        tick_sec += step
    ticks.append((1.0, "0 s"))
    return ticks


def generate_nice_value_ticks(
    data_min: float, data_max: float, target_count: int = 5,
) -> tuple[float, float, list[str]]:
    """Return a padded numeric domain and human-friendly evenly spaced labels."""
    data_min = float(data_min)
    data_max = float(data_max)
    if data_min > data_max:
        data_min, data_max = data_max, data_min
    if data_min == data_max:
        pad = max(1.0, abs(data_min) * 0.05)
        data_min -= pad
        data_max += pad
    count = max(2, int(target_count))
    raw_step = (data_max - data_min) / max(1, count - 1)
    magnitude = 10 ** int(math.floor(math.log10(raw_step)))
    normalized = raw_step / magnitude
    if normalized <= 1:
        multiplier = 1
    elif normalized <= 2:
        multiplier = 2
    elif normalized <= 5:
        multiplier = 5
    else:
        multiplier = 10
    step = multiplier * magnitude
    nice_min = math.floor(data_min / step) * step
    nice_max = math.ceil(data_max / step) * step
    labels = [
        f"{nice_min + i * step:.0f}"
        for i in range(int(round((nice_max - nice_min) / step)) + 1)
    ]
    return nice_min, nice_max, labels


def _history_chart_cache_key(
    history_values, width, height, line_color, line_thickness, fill_alpha,
    fill_color, show_axes, grid_color, time_labels, value_labels, supersample,
    custom_min_val, custom_max_val, label_count, label_units, unit,
    show_average, label_font_size, font_path,
    show_x_axis_values=True, show_y_axis_values=True,
    axis_font_size=None, axis_outline=0,
) -> tuple:
    chart_start_dt = getattr(history_values, "chart_start_dt", None)
    chart_end_dt = getattr(history_values, "chart_end_dt", None)
    time_scope = getattr(history_values, "time_scope", "activity")
    history_identity = getattr(
        history_values, "_chart_cache_token", id(history_values) if history_values else None
    )
    return (
        history_identity,
        len(history_values) if history_values else 0,
        chart_start_dt, chart_end_dt, time_scope,
        width, height, tuple(line_color), line_thickness, fill_alpha,
        tuple(fill_color) if fill_color else None, show_axes,
        tuple(grid_color) if grid_color else None,
        tuple(time_labels) if time_labels else None,
        tuple(value_labels) if value_labels else None,
        supersample, custom_min_val, custom_max_val, label_count,
        label_units, unit, show_average, label_font_size, font_path,
        bool(show_x_axis_values), bool(show_y_axis_values),
        axis_font_size, int(axis_outline),
    )


def generate_history_chart(
    history_values: list[float],
    width: int,
    height: int,
    line_color: tuple[int, int, int] = (255, 0, 0),
    line_thickness: int = 3,
    fill_alpha: int = 50,
    fill_color: Optional[tuple[int, int, int]] = None,
    current_index: Optional[int | tuple[float, float]] = None,
    cursor_color: tuple[int, int, int] = (255, 255, 255),
    show_axes: bool = True,
    grid_color: Optional[tuple[int, int, int, int]] = None,
    time_labels: Optional[list[str] | list[tuple[float, str]]] = None,
    value_labels: Optional[list[str]] = None,
    supersample: int = 1,
    custom_min_val: Optional[float] = None,
    custom_max_val: Optional[float] = None,
    label_count: int = 2,
    label_units: bool = False,
    unit: str = "",
    show_average: bool = False,
    label_font_size: Optional[float] = None,
    font_path: Optional[str] = None,
    show_x_axis_values: bool = True,
    show_y_axis_values: bool = True,
    axis_font_size: Optional[float] = None,
    axis_outline: int = 0,
) -> Image.Image:
    """Generate a universal line chart with transparent fill, axes, and optional cursor."""
    profiler = get_overlay_profiler()
    lookup_started = time.perf_counter()
    cache_key = _history_chart_cache_key(
        history_values, width, height, line_color, line_thickness, fill_alpha,
        fill_color, show_axes, grid_color, time_labels, value_labels,
        supersample, custom_min_val, custom_max_val, label_count, label_units,
        unit, show_average, label_font_size, font_path,
        show_x_axis_values=show_x_axis_values, show_y_axis_values=show_y_axis_values,
        axis_font_size=axis_font_size, axis_outline=axis_outline,
    )

    bg_data = _CHART_BG_CACHE.get(cache_key)
    profiler.record(
        "graph.background_cache_lookup",
        (time.perf_counter() - lookup_started) * 1000.0,
    )
    if bg_data is None:
        background_started = time.perf_counter()
        bg_data = _build_chart_bg(
            history_values=history_values, width=width, height=height,
            line_color=line_color, line_thickness=line_thickness,
            fill_alpha=fill_alpha, fill_color=fill_color,
            show_axes=show_axes, grid_color=grid_color,
            time_labels=time_labels, value_labels=value_labels,
            supersample=supersample, custom_min_val=custom_min_val,
            custom_max_val=custom_max_val, label_count=label_count,
            label_units=label_units, unit=unit, show_average=show_average,
            label_font_size=label_font_size, font_path=font_path,
            show_x_axis_values=show_x_axis_values,
            show_y_axis_values=show_y_axis_values,
            axis_font_size=axis_font_size, axis_outline=axis_outline,
        )
        if len(_CHART_BG_CACHE) > 50:
            _CHART_BG_CACHE.clear()
        _CHART_BG_CACHE[cache_key] = bg_data
        profiler.record(
            "graph.background_axes_grid_polyline",
            (time.perf_counter() - background_started) * 1000.0,
        )

    bg_img, points, plot_y1, plot_y2, calc_thickness = bg_data

    if current_index is None or not points:
        return bg_img

    if isinstance(current_index, (tuple, list)) and len(current_index) == 2:
        cursor_x, py = float(current_index[0]), float(current_index[1])
    elif isinstance(current_index, int) and 0 <= current_index < len(points):
        cursor_x, py = points[current_index]
    else:
        return bg_img

    cursor_started = time.perf_counter()
    img = bg_img.copy()
    draw = ImageDraw.Draw(img)
    draw.line(
        (cursor_x, plot_y1, cursor_x, plot_y2),
        fill=(cursor_color[0], cursor_color[1], cursor_color[2], 200),
        width=max(2, calc_thickness),
    )
    dot_r = max(3, calc_thickness + 1)
    draw.ellipse(
        (cursor_x - dot_r, py - dot_r, cursor_x + dot_r, py + dot_r),
        fill=(cursor_color[0], cursor_color[1], cursor_color[2], 255),
        outline=(line_color[0], line_color[1], line_color[2], 255),
    )
    profiler.record(
        "graph.current_cursor",
        (time.perf_counter() - cursor_started) * 1000.0,
    )
    return img


def get_history_chart_background(
    history_values: list[float], width: int, height: int,
    line_color=(255, 0, 0), line_thickness=3, fill_alpha=50,
    fill_color=None, show_axes=True, grid_color=None, time_labels=None,
    value_labels=None, supersample=1, custom_min_val=None,
    custom_max_val=None, label_count=2, label_units=False, unit="",
    show_average=False, label_font_size=None, font_path=None,
    show_x_axis_values=True, show_y_axis_values=True,
    axis_font_size=None, axis_outline=0,
):
    """Return immutable background geometry and its complete cache identity."""
    cache_key = _history_chart_cache_key(
        history_values, width, height, line_color, line_thickness, fill_alpha,
        fill_color, show_axes, grid_color, time_labels, value_labels,
        supersample, custom_min_val, custom_max_val, label_count, label_units,
        unit, show_average, label_font_size, font_path,
        show_x_axis_values=show_x_axis_values, show_y_axis_values=show_y_axis_values,
        axis_font_size=axis_font_size, axis_outline=axis_outline,
    )
    if cache_key not in _CHART_BG_CACHE:
        generate_history_chart(
            history_values, width, height, line_color=line_color,
            line_thickness=line_thickness, fill_alpha=fill_alpha,
            fill_color=fill_color, current_index=None, show_axes=show_axes,
            grid_color=grid_color, time_labels=time_labels,
            value_labels=value_labels, supersample=supersample,
            custom_min_val=custom_min_val, custom_max_val=custom_max_val,
            label_count=label_count, label_units=label_units, unit=unit,
            show_average=show_average, label_font_size=label_font_size,
            font_path=font_path,
            show_x_axis_values=show_x_axis_values,
            show_y_axis_values=show_y_axis_values,
            axis_font_size=axis_font_size, axis_outline=axis_outline,
        )
    return (*_CHART_BG_CACHE[cache_key], cache_key)


def get_history_chart_prefix_background(
    history_values: list[float], visible_end_dt, width: int, height: int,
    line_color=(255, 0, 0), line_thickness=3, fill_alpha=50,
    fill_color=None, show_axes=True, grid_color=None, time_labels=None,
    value_labels=None, supersample=1, custom_min_val=None,
    custom_max_val=None, label_count=2, label_units=False, unit="",
    show_average=False, label_font_size=None, font_path=None,
    show_x_axis_values=True, show_y_axis_values=True,
    axis_font_size=None, axis_outline=0,
):
    """Render only the activity-history prefix ending at ``visible_end_dt``.

    Axes and full-history geometry use the fixed activity domain and are
    immutable/cached. Per frame this function only bisects the current time,
    reveals the corresponding immutable point prefix, and draws its existing
    segment ranges. It never rescales the past into the current-time domain.
    """
    profiler = get_overlay_profiler()
    timestamps = getattr(history_values, "timestamps", None)
    if not timestamps or len(timestamps) != len(history_values) or visible_end_dt is None:
        return get_history_chart_background(
            history_values, width, height, line_color=line_color,
            line_thickness=line_thickness, fill_alpha=fill_alpha,
            fill_color=fill_color, show_axes=show_axes, grid_color=grid_color,
            time_labels=time_labels, value_labels=value_labels,
            supersample=supersample, custom_min_val=custom_min_val,
            custom_max_val=custom_max_val, label_count=label_count,
            label_units=label_units, unit=unit, show_average=show_average,
            label_font_size=label_font_size, font_path=font_path,
            show_x_axis_values=show_x_axis_values,
            show_y_axis_values=show_y_axis_values,
            axis_font_size=axis_font_size, axis_outline=axis_outline,
        )

    cache_key = _history_chart_cache_key(
        history_values, width, height, line_color, line_thickness, fill_alpha,
        fill_color, show_axes, grid_color, time_labels, value_labels,
        supersample, custom_min_val, custom_max_val, label_count, label_units,
        unit, show_average, label_font_size, font_path,
        show_x_axis_values=show_x_axis_values, show_y_axis_values=show_y_axis_values,
        axis_font_size=axis_font_size, axis_outline=axis_outline,
    )
    geometry = _CHART_PREFIX_GEOMETRY_CACHE.get(cache_key)
    if geometry is None:
        geometry = _build_chart_bg(
            history_values=history_values, width=width, height=height,
            line_color=line_color, line_thickness=line_thickness,
            fill_alpha=fill_alpha, fill_color=fill_color,
            show_axes=show_axes, grid_color=grid_color,
            time_labels=time_labels, value_labels=value_labels,
            supersample=supersample, custom_min_val=custom_min_val,
            custom_max_val=custom_max_val, label_count=label_count,
            label_units=label_units, unit=unit, show_average=show_average,
            label_font_size=label_font_size, font_path=font_path,
            draw_series=False,
            show_x_axis_values=show_x_axis_values,
            show_y_axis_values=show_y_axis_values,
            axis_font_size=axis_font_size, axis_outline=axis_outline,
        )
        if len(_CHART_PREFIX_GEOMETRY_CACHE) > 50:
            _CHART_PREFIX_GEOMETRY_CACHE.clear()
        _CHART_PREFIX_GEOMETRY_CACHE[cache_key] = geometry

    axes_img, full_points, plot_y1, plot_y2, calc_thickness = geometry
    metadata_started = time.perf_counter()
    meta_key = ("meta", cache_key)
    metadata = _CHART_PREFIX_GEOMETRY_CACHE.get(meta_key)
    if metadata is None:
        sample_tz = timestamps[0].tzinfo

        def align(value):
            if sample_tz is None:
                return value.replace(tzinfo=None) if value.tzinfo is not None else value
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

        aligned_timestamps = tuple(align(ts) for ts in timestamps)
        chart_start = align(getattr(history_values, "chart_start_dt", None) or timestamps[0])
        chart_end = align(getattr(history_values, "chart_end_dt", None) or timestamps[-1])
        full_span = max(0.0, (chart_end - chart_start).total_seconds())
        norm_first = max(0.0, min(1.0, (aligned_timestamps[0] - chart_start).total_seconds() / full_span)) if full_span else 0.0
        norm_last = max(0.0, min(1.0, (aligned_timestamps[-1] - chart_start).total_seconds() / full_span)) if full_span else 0.0
        if full_points and norm_last > norm_first:
            plot_w = (full_points[-1][0] - full_points[0][0]) / (norm_last - norm_first)
            plot_x1 = full_points[0][0] - norm_first * plot_w
            plot_x2 = plot_x1 + plot_w
        elif full_points:
            plot_x1, plot_x2 = full_points[0][0], full_points[-1][0]
        else:
            plot_x1 = plot_x2 = 0.0
        ranges = _chart_segment_ranges(timestamps, history_values)
        cumulative_sum = []
        cumulative_count = []
        running_sum = 0.0
        running_count = 0
        for value in history_values:
            if value is not None:
                running_sum += float(value)
                running_count += 1
            cumulative_sum.append(running_sum)
            cumulative_count.append(running_count)
        numeric_values = [float(value) for value in history_values if value is not None]
        metadata = {
            "sample_tz": sample_tz,
            "aligned_timestamps": aligned_timestamps,
            "chart_start": chart_start,
            "chart_end": chart_end,
            "full_span": full_span,
            "plot_x1": plot_x1,
            "plot_x2": plot_x2,
            "ranges": ranges,
            "cumulative_sum": tuple(cumulative_sum),
            "cumulative_count": tuple(cumulative_count),
            "data_min": min(numeric_values) if numeric_values else 0.0,
            "data_max": max(numeric_values) if numeric_values else 100.0,
        }
        if len(_CHART_PREFIX_GEOMETRY_CACHE) > 50:
            _CHART_PREFIX_GEOMETRY_CACHE.clear()
        _CHART_PREFIX_GEOMETRY_CACHE[meta_key] = metadata
    profiler.record("graph.prefix.geometry_cache", (time.perf_counter() - metadata_started) * 1000.0)

    sample_tz = metadata["sample_tz"]
    current_end = visible_end_dt
    if sample_tz is None:
        current_end = current_end.replace(tzinfo=None) if current_end.tzinfo is not None else current_end
    elif current_end.tzinfo is None:
        current_end = current_end.replace(tzinfo=timezone.utc)
    aligned_timestamps = metadata["aligned_timestamps"]
    chart_start = metadata["chart_start"]
    chart_end = metadata["chart_end"]
    full_span = metadata["full_span"]
    if current_end < chart_start:
        return axes_img.copy(), full_points, plot_y1, plot_y2, calc_thickness, cache_key

    if current_end >= chart_end:
        # This is the exact full-history endpoint, including its original
        # polygon/line raster and anti-aliasing.
        return get_history_chart_background(
            history_values, width, height, line_color=line_color,
            line_thickness=line_thickness, fill_alpha=fill_alpha,
            fill_color=fill_color, show_axes=show_axes, grid_color=grid_color,
            time_labels=time_labels, value_labels=value_labels,
            supersample=supersample, custom_min_val=custom_min_val,
            custom_max_val=custom_max_val, label_count=label_count,
            label_units=label_units, unit=unit, show_average=show_average,
            label_font_size=label_font_size, font_path=font_path,
            axis_font_size=axis_font_size, axis_outline=axis_outline,
        )

    bisect_started = time.perf_counter()
    visible_count = bisect_right(aligned_timestamps, current_end)
    profiler.record("graph.prefix.bisect_current", (time.perf_counter() - bisect_started) * 1000.0)
    if visible_count <= 0:
        return axes_img.copy(), full_points, plot_y1, plot_y2, calc_thickness, cache_key

    if not full_points or full_span <= 0:
        return axes_img.copy(), full_points, plot_y1, plot_y2, calc_thickness, cache_key
    plot_x1 = metadata["plot_x1"]
    plot_x2 = metadata["plot_x2"]

    point_started = time.perf_counter()
    # ``full_points`` was built once using chart_start -> chart_end.  Slicing
    # preserves every sample's X coordinate, keeps proportional FIT gaps, and
    # leaves the future part of the plot transparent.
    prefix_points = full_points[:visible_count]
    profiler.record("graph.prefix.point_prefix", (time.perf_counter() - point_started) * 1000.0)

    ranges = metadata["ranges"]
    segment_started = time.perf_counter()
    visible_ranges = [
        (max(0, start), min(visible_count, end))
        for start, end in ranges if start < visible_count and end > 0
    ]
    profiler.record("graph.prefix.segment_selection", (time.perf_counter() - segment_started) * 1000.0)

    copy_started = time.perf_counter()
    img = axes_img.copy()
    profiler.record("graph.prefix.image_copy", (time.perf_counter() - copy_started) * 1000.0)
    draw = ImageDraw.Draw(img)
    actual_fill_rgb = fill_color if fill_color is not None else line_color
    actual_fill = (actual_fill_rgb[0], actual_fill_rgb[1], actual_fill_rgb[2], fill_alpha)
    fill_started = time.perf_counter()
    for left, right in visible_ranges:
        segment = prefix_points[left:right]
        if len(segment) >= 2:
            polygon = list(segment)
            polygon.extend(((segment[-1][0], plot_y2), (segment[0][0], plot_y2)))
            draw.polygon(polygon, fill=actual_fill)
    profiler.record("graph.prefix.fill_polygon", (time.perf_counter() - fill_started) * 1000.0)

    line_started = time.perf_counter()
    for left, right in visible_ranges:
        segment = prefix_points[left:right]
        if len(segment) >= 2:
            draw.line(segment, fill=(*line_color, 255), width=max(1, calc_thickness), joint="round")
    profiler.record("graph.prefix.line_draw", (time.perf_counter() - line_started) * 1000.0)

    if show_axes:
        # Keep structural pixels above the prefix fill/line exactly as in the
        # full chart path, including grid, ticks, labels, and their outline.
        img.paste(axes_img, (0, 0), axes_img)

    if show_average:
        average_started = time.perf_counter()
        visible_sum = metadata["cumulative_sum"][visible_count - 1]
        visible_count_numeric = metadata["cumulative_count"][visible_count - 1]
        if visible_count_numeric:
            data_min = float(custom_min_val) if custom_min_val is not None else metadata["data_min"]
            data_max = float(custom_max_val) if custom_max_val is not None else metadata["data_max"]
            if data_min >= data_max:
                data_max = data_min + 1.0
            if _AVERAGE_LAYER_CACHE_ENABLED:
                average_layer, _average_values = _get_cached_average_layer(
                    history_values, visible_count - 1,
                    plot_x1, plot_x2, prefix_points[-1][0], plot_y1, plot_y2,
                    data_min, data_max, visible_sum, visible_count_numeric,
                    width, height, supersample,
                )
                if average_layer is not None:
                    average_mask, (average_x, average_y) = average_layer
                    draw.bitmap(
                        (average_x, average_y), average_mask,
                        fill=(255, 200, 0, 220),
                    )
            else:
                avg_val = visible_sum / visible_count_numeric
                if data_min <= avg_val <= data_max:
                    avg_y = plot_y2 - ((avg_val - data_min) / (data_max - data_min)) * (plot_y2 - plot_y1)
                    visible_x2 = max(plot_x1, min(plot_x2, prefix_points[-1][0]))
                    for x in range(int(plot_x1), int(visible_x2), 6 * max(1, int(supersample))):
                        draw.line((x, avg_y, min(x + 3 * max(1, int(supersample)), visible_x2), avg_y), fill=(255, 200, 0, 220), width=max(1, int(supersample)))
        profiler.record("graph.prefix.average", (time.perf_counter() - average_started) * 1000.0)

    return img, full_points, plot_y1, plot_y2, calc_thickness, cache_key


def _build_chart_bg(
    history_values: list[float],
    width: int,
    height: int,
    line_color: tuple[int, int, int],
    line_thickness: int,
    fill_alpha: int,
    fill_color: Optional[tuple[int, int, int]],
    show_axes: bool,
    grid_color: Optional[tuple[int, int, int, int]],
    time_labels: Optional[list[str] | list[tuple[float, str]]],
    value_labels: Optional[list[str]],
    supersample: int,
    custom_min_val: Optional[float],
    custom_max_val: Optional[float],
    label_count: int,
    label_units: bool,
    unit: str,
    show_average: bool,
    label_font_size: Optional[float],
    font_path: Optional[str],
    draw_series: bool = True,
    show_x_axis_values: bool = True,
    show_y_axis_values: bool = True,
    axis_font_size: Optional[float] = None,
    axis_outline: int = 0,
) -> tuple[Image.Image, list[tuple[float, float]], float, float, int]:
    """Build and return static chart background (image, points, plot_y1, plot_y2, thickness)."""
    ss = max(1, int(supersample))
    out_w, out_h = width, height
    width *= ss
    height *= ss
    calc_line_thickness = line_thickness * ss
    has_data = history_values and len(history_values) >= 1

    numeric_values = [float(value) for value in history_values if value is not None]
    if numeric_values:
        data_min = min(numeric_values)
        data_max = max(numeric_values)
    else:
        data_min = 0.0
        data_max = 100.0

    if custom_min_val is None and custom_max_val is None:
        min_val, max_val, auto_value_labels = generate_nice_value_ticks(
            data_min, data_max, label_count,
        )
    else:
        min_val = custom_min_val if custom_min_val is not None else data_min
        max_val = custom_max_val if custom_max_val is not None else data_max
        auto_value_labels = None
    if min_val >= max_val:
        max_val = min_val + 1.0

    val_range = max_val - min_val
    num_points = len(history_values) if has_data else 0

    count = max(2, label_count)
    base_value_labels = value_labels or auto_value_labels or [
        f"{min_val + (i / (count - 1)) * val_range:.0f}"
        for i in range(count)
    ]
    y_label_values = [
        str(lbl) + (f" {unit}" if (label_units and unit) else "")
        for lbl in base_value_labels
    ]
    if time_labels:
        if isinstance(time_labels[0], (tuple, list)):
            x_ticks = list(time_labels)
        else:
            x_ticks = [
                (i / max(1, len(time_labels) - 1), str(lbl))
                for i, lbl in enumerate(time_labels)
            ]
    else:
        x_ticks = [(i / 4.0, lbl) for i, lbl in enumerate(["0%", "25%", "50%", "75%", "100%"])]

    axis_cache_key = (
        "chart_axis_v3", width, height, ss, bool(show_axes),
        tuple(grid_color) if grid_color is not None else None,
        tuple(y_label_values), tuple(x_ticks),
        label_font_size, font_path, axis_font_size, int(axis_outline),
        bool(show_x_axis_values), bool(show_y_axis_values),
    )
    cached_axis = _CHART_AXIS_CACHE.get(axis_cache_key)
    axis_cache_hit = cached_axis is not None
    if axis_cache_hit:
        img, plot_x1, plot_y1, plot_x2, plot_y2 = cached_axis
        img = img.copy()
        axis_layer = img.copy()
        draw = ImageDraw.Draw(img)
        font_axis = None
    else:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

    if not axis_cache_hit:
        axis_bottom_margin_est = (int(max(6, height * 0.20)) if show_axes else 0) * ss
        try:
            plot_h_est = max(1, height - 4 * ss - axis_bottom_margin_est)
            effective_axis_size = (
                label_font_size if label_font_size and label_font_size > 0
                else axis_font_size
            )
            if effective_axis_size and effective_axis_size > 0:
                label_fs = int(effective_axis_size * ss)
            else:
                label_fs = int(max(7, min(width, height) * 0.13) * ss)
            label_fs = max(6, min(label_fs, max(6, plot_h_est // 2)))
            if font_path:
                font_axis = load_font(font_path, label_fs)
            else:
                font_axis = load_font_cache_small(label_fs)
        except Exception:
            font_axis = None

    if not axis_cache_hit and show_axes:
        max_label_w = 0
        max_y_bot = 0
        max_y_top = 0
        for lbl in y_label_values:
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                max_y_bot = max(max_y_bot, bbox[3])
                max_y_top = max(max_y_top, -bbox[1] if bbox[1] < 0 else 0)
            else:
                tw = len(lbl) * 6
                th = 10
                max_y_bot = max(max_y_bot, 10)
            max_label_w = max(max_label_w, tw)

        max_x_bot = 0
        max_x_label_w = 0
        for norm_x, lbl in x_ticks:
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                max_x_bot = max(max_x_bot, bbox[3])
                max_x_label_w = max(max_x_label_w, bbox[2] - bbox[0])
            else:
                max_x_bot = max(max_x_bot, 10)
                max_x_label_w = max(max_x_label_w, len(lbl) * 6)

        axis_left_margin = int(math.ceil(max_label_w + 8 * ss + 2 * ss))
        axis_right_margin = int(math.ceil(max(6 * ss, max_x_label_w // 2 + 4 * ss)))
        axis_top_margin = int(math.ceil(max(4 * ss, max_y_bot / 2.0 + max_y_top + 4 * ss)))
        needed_bottom_margin = int(math.ceil(max_x_bot + 10 * ss))
        axis_bottom_margin = max(axis_bottom_margin_est, needed_bottom_margin)
    elif not axis_cache_hit:
        axis_left_margin = 0
        axis_right_margin = 4 * ss
        axis_top_margin = 4 * ss
        axis_bottom_margin = 4 * ss

    if not axis_cache_hit:
        plot_x1 = axis_left_margin
        plot_y1 = axis_top_margin
        plot_x2 = width - axis_right_margin
        plot_y2 = height - axis_bottom_margin
        plot_w = max(1, plot_x2 - plot_x1)
        plot_h = max(1, plot_y2 - plot_y1)
    else:
        plot_w = max(1, plot_x2 - plot_x1)
        plot_h = max(1, plot_y2 - plot_y1)
    # These are chart-structure colors, deliberately independent of
    # ``fill_alpha``.  The axis image is composited again after the series so
    # the fill can never attenuate grid/tick/label pixels.
    axis_color = (180, 180, 180, 255)
    tick_color = (150, 150, 150, 255)
    label_color = (200, 200, 200, 255)
    # Grid alpha is a chart-style input, not the series fill alpha.  Store
    # grid strokes as opaque structural pixels so their final color cannot
    # change when the fill beneath them changes.
    grid_render_color = (
        (*grid_color[:3], 255) if grid_color is not None else None
    )

    if not axis_cache_hit and show_axes:
        draw.line((plot_x1, plot_y1, plot_x1, plot_y2), fill=axis_color, width=max(1, ss))
        draw.line((plot_x1, plot_y2, plot_x2, plot_y2), fill=axis_color, width=max(1, ss))

        y_positions = [
            plot_y2 - (i / max(1, len(y_label_values) - 1)) * plot_h
            for i in range(len(y_label_values))
        ]

        for lbl, yp in zip(y_label_values, y_positions):
            if grid_render_color is not None:
                draw.line(
                    (plot_x1, yp, plot_x2, yp),
                    fill=grid_render_color, width=max(1, ss),
                )
            draw.line((plot_x1 - 4 * ss, yp, plot_x1, yp), fill=tick_color, width=max(1, ss))
            if show_y_axis_values:
                if font_axis:
                    bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    b_bot = bbox[3]
                    b_top = bbox[1]
                else:
                    tw = len(lbl) * 6
                    th = 10
                    b_bot = 10
                    b_top = 0
                tx = max(2 * ss, plot_x1 - tw - 5 * ss)
                ty = int(round(yp - (b_bot + b_top) / 2.0))
                ty = max(2 * ss - b_top, min(height - b_bot - 2 * ss, ty))
                if font_axis:
                    draw.text(
                        (tx, ty), lbl, fill=label_color, font=font_axis,
                        stroke_width=max(0, int(axis_outline * ss)),
                        stroke_fill=(0, 0, 0, 255),
                    )
                else:
                    draw.text((tx, ty), lbl, fill=label_color)

        for norm_x, lbl in x_ticks:
            x = plot_x1 + plot_w * norm_x
            draw.line((x, plot_y2, x, plot_y2 + 4 * ss), fill=tick_color, width=max(1, ss))
            if show_x_axis_values:
                if font_axis:
                    bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                    tw = bbox[2] - bbox[0]
                    b_bot = bbox[3]
                else:
                    tw = len(lbl) * 6
                    bbox = (0, 0, tw, 10)
                    b_bot = 10

                if norm_x <= 0.01:
                    tx = max(2 * ss, int(round(x - max(0, bbox[0]))))
                elif norm_x >= 0.99:
                    tx = min(width - tw - 2 * ss, int(round(x - tw)))
                else:
                    tx = int(round(x - tw / 2.0))
                    tx = max(2 * ss, min(width - tw - 2 * ss, tx))

                ty = plot_y2 + 5 * ss
                ty = min(height - b_bot - 2 * ss, ty)
                if font_axis:
                    draw.text(
                        (tx, ty), lbl, fill=label_color, font=font_axis,
                        stroke_width=max(0, int(axis_outline * ss)),
                        stroke_fill=(0, 0, 0, 255),
                    )
                else:
                    draw.text((tx, ty), lbl, fill=label_color)

    if not axis_cache_hit:
        axis_layer = img.copy()
        if len(_CHART_AXIS_CACHE) >= 64:
            _CHART_AXIS_CACHE.clear()
        _CHART_AXIS_CACHE[axis_cache_key] = (img.copy(), plot_x1, plot_y1, plot_x2, plot_y2)

    points: list[tuple[float, float]] = []
    if has_data:
        timestamps = getattr(history_values, "timestamps", None)
        chart_start_dt = getattr(history_values, "chart_start_dt", None)
        chart_end_dt = getattr(history_values, "chart_end_dt", None)
        t_start = chart_start_dt or (timestamps[0] if timestamps else None)
        t_end = chart_end_dt or (timestamps[-1] if timestamps else None)

        if (
            timestamps
            and len(timestamps) == len(history_values)
            and t_start is not None
            and t_end is not None
            and t_end > t_start
        ):
            tz = timestamps[0].tzinfo
            if tz is None:
                if t_start.tzinfo is not None:
                    t_start = t_start.replace(tzinfo=None)
                if t_end.tzinfo is not None:
                    t_end = t_end.replace(tzinfo=None)
            else:
                if t_start.tzinfo is None:
                    t_start = t_start.replace(tzinfo=timezone.utc)
                if t_end.tzinfo is None:
                    t_end = t_end.replace(tzinfo=timezone.utc)

            total_sec = (t_end - t_start).total_seconds()
            for ts, val in zip(timestamps, history_values):
                st = ts
                if tz is None and st.tzinfo is not None:
                    st = st.replace(tzinfo=None)
                elif tz is not None and st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                norm_x = (st - t_start).total_seconds() / total_sec
                norm_x = max(0.0, min(1.0, norm_x))
                x = plot_x1 + norm_x * plot_w
                y = (
                    plot_y2 - ((val - min_val) / val_range) * plot_h
                    if val is not None else plot_y2
                )
                points.append((x, y))
        else:
            for i, val in enumerate(history_values):
                x = plot_x1 + (i / (num_points - 1)) * plot_w if num_points > 1 else plot_x1
                y = (
                    plot_y2 - ((val - min_val) / val_range) * plot_h
                    if val is not None else plot_y2
                )
                points.append((x, y))

        if points and draw_series:
            segments = _split_chart_segments(points, timestamps, history_values)
            actual_fill_rgb = fill_color if fill_color is not None else line_color
            actual_fill = (actual_fill_rgb[0], actual_fill_rgb[1], actual_fill_rgb[2], fill_alpha)
            for segment in segments:
                if len(segment) >= 2:
                    fill_polygon: list[tuple[float, float]] = list(segment)
                    fill_polygon.append((segment[-1][0], plot_y2))
                    fill_polygon.append((segment[0][0], plot_y2))
                    draw.polygon(fill_polygon, fill=actual_fill)

            for segment in segments:
                if len(segment) >= 2:
                    draw.line(segment, fill=(line_color[0], line_color[1], line_color[2], 255), width=calc_line_thickness, joint="round")

            if show_axes:
                # Restore the complete immutable axis/grid/tick/label layer
                # after the translucent fill and opaque line.
                img.paste(axis_layer, (0, 0), axis_layer)

        if show_average and draw_series and numeric_values:
            avg_val = float(sum(numeric_values) / len(numeric_values))
            if min_val <= avg_val <= max_val:
                avg_y = plot_y2 - ((avg_val - min_val) / val_range) * plot_h
                avg_color = (255, 200, 0, 220)
                for x in range(int(plot_x1), int(plot_x2), 6 * ss):
                    draw.line((x, avg_y, min(x + 3 * ss, plot_x2), avg_y), fill=avg_color, width=max(1, ss))

    if ss > 1:
        img = img.resize((out_w, out_h), Image.LANCZOS)
        # Rescale points and margins to output dimensions
        scale_x = out_w / width
        scale_y = out_h / height
        points = [(px * scale_x, py * scale_y) for px, py in points]
        plot_y1 *= scale_y
        plot_y2 *= scale_y
        calc_line_thickness = line_thickness

    return img, points, plot_y1, plot_y2, calc_line_thickness
