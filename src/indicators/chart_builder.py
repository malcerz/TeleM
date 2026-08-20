"""Chart data builder — pre-compute chart history for all chart-type indicators.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

from bisect import bisect_right, bisect_left
from datetime import datetime, timezone
from itertools import count
from typing import Any, Callable


_CHART_HISTORY_CACHE_TOKENS = count()


class ChartHistory(list[float]):
    """Values plus the immutable timestamps and axis bounds used to build the history.

    It remains a normal list for existing renderers and callers, while the
    shared frame-data path can clip it by absolute telemetry time without
    scanning or copying the complete source series on every frame.
    """

    __slots__ = (
        "timestamps", "chart_start_dt", "chart_end_dt", "time_scope",
        "_chart_cache_token",
    )

    def __init__(
        self,
        values: list[float],
        timestamps: list[datetime],
        chart_start_dt: datetime | None = None,
        chart_end_dt: datetime | None = None,
        time_scope: str = "activity",
    ):
        super().__init__(values)
        self.timestamps = tuple(timestamps)
        self.chart_start_dt = chart_start_dt if chart_start_dt is not None else (timestamps[0] if timestamps else None)
        self.chart_end_dt = chart_end_dt if chart_end_dt is not None else (timestamps[-1] if timestamps else None)
        self.time_scope = time_scope
        # ``id(self)`` is not a safe immutable-history identity: Python may
        # reuse an object ID after a temporary prefix view is released.  A
        # monotonic token keeps worker-local chart caches isolated without
        # hashing or copying the complete history on every frame.
        self._chart_cache_token = next(_CHART_HISTORY_CACHE_TOKENS)


def clip_chart_data(
    chart_data: dict[str, list[float]],
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    *args,
    **kwargs,
) -> dict[str, list[float]]:
    """Return a timestamp-bounded, non-mutating view of chart histories for [start_dt, end_dt].

    If start_dt and end_dt are None, returns chart_data unmodified.
    """
    if start_dt is None and end_dt is None:
        return chart_data

    clipped: dict[str, list[float]] = {}
    for key, values in chart_data.items():
        timestamps = getattr(values, "timestamps", None)
        if not timestamps:
            clipped[key] = values
            continue
        sample_tz = timestamps[0].tzinfo
        def align(bound: datetime | None) -> datetime | None:
            if bound is None:
                return None
            if sample_tz is None:
                return bound.replace(tzinfo=None)
            if bound.tzinfo is None:
                return bound.replace(tzinfo=timezone.utc)
            return bound

        start_bound = align(start_dt)
        end_bound = align(end_dt)
        start = bisect_left(timestamps, start_bound) if start_bound is not None else 0
        end = bisect_right(timestamps, end_bound) if end_bound is not None else len(timestamps)
        scope = getattr(values, "time_scope", "activity")
        if end <= start:
            clipped[key] = ChartHistory([], [], chart_start_dt=start_bound, chart_end_dt=end_bound, time_scope=scope)
        else:
            clipped[key] = ChartHistory(
                list(values[start:end]),
                list(timestamps[start:end]),
                chart_start_dt=start_bound or timestamps[start],
                chart_end_dt=end_bound or timestamps[end - 1],
                time_scope=scope,
            )
    return clipped


def build_chart_data(
    layout: dict[str, Any],
    get_samples_fn: Callable[[str], tuple[list, list, list]],
    resolve_samples_fn: Callable[[str, str, str | None], list],
    start_dt_utc: datetime | None = None,
    end_dt_utc: datetime | None = None,
    source_activity_ranges: dict[str, tuple[datetime, datetime]] | None = None,
) -> dict[str, list[float]]:
    """Build chart history data for all chart-type indicators in a layout.

    This function is shared by the preview (hud_tuner_app.py) and the
    render pipeline (ffmpeg_pipeline.py) to eliminate code duplication
    and ensure identical behaviour in both paths.

    Args:
        layout: HUD layout dict with ``indicators`` key.
        get_samples_fn: ``(source) -> (speed, track, alt)`` triple.
        resolve_samples_fn: ``(field_name) -> list`` for non-speed/alt/dist.
        start_dt_utc: Optional video-visible start time for range bounding.
        end_dt_utc: Optional video-visible end time for range bounding.
        source_activity_ranges: Optional dict mapping source name ("fit", "gpx", "gpmf")
            to (global_activity_start_dt, global_activity_end_dt).

    Returns:
        ``{indicator_key: [values]}`` for every enabled chart indicator.
    """
    chart_data: dict[str, list[float]] = {}
    for ind_key, ind_cfg in layout.get("indicators", {}).items():
        if ind_cfg.get("form") != "chart" or not ind_cfg.get("enabled", True):
            continue
        src = ind_cfg.get("source", "gpmf")
        scope = ind_cfg.get("chart_time_scope", "activity")
        if ind_key.startswith("fit_") and ind_key.endswith("_text"):
            field_name = ind_key[4:-5]
            samples = resolve_samples_fn(field_name, "fit", ind_key)
        elif "speed" in ind_key:
            spd_s, _, _ = get_samples_fn(src)
            samples = spd_s or []
        elif "dist" in ind_key:
            _, trk_s, _ = get_samples_fn(src)
            samples = trk_s or []
        elif "alt" in ind_key:
            _, _, alt_s = get_samples_fn(src)
            samples = alt_s or []
        elif "power" in ind_key:
            samples = resolve_samples_fn("power", src, ind_key)
        elif "hr" in ind_key:
            samples = resolve_samples_fn("hr", src, ind_key)
        elif "cad" in ind_key:
            samples = resolve_samples_fn("cad", src, ind_key)
        elif "atemp" in ind_key:
            samples = resolve_samples_fn("atemp", src, ind_key)
        elif "battery" in ind_key:
            samples = resolve_samples_fn("battery", src, ind_key)
        elif "iso" in ind_key:
            samples = resolve_samples_fn("iso", src, ind_key)
        elif "exposure" in ind_key:
            samples = resolve_samples_fn("exposure", src, ind_key)
        elif "temp" in ind_key and "atemp" not in ind_key:
            samples = resolve_samples_fn("temperature", src, ind_key)
        elif ind_key in {
            "accel_x_text", "accel_y_text", "accel_z_text", "accel_magnitude_text",
            "gyro_x_text", "gyro_y_text", "gyro_z_text", "gyro_magnitude_text",
        }:
            samples = resolve_samples_fn(ind_key[:-5], src, ind_key)
        else:
            samples = []

        if samples:
            sample_ts = [sample[0] for sample in samples]
            sample_tz = sample_ts[0].tzinfo if sample_ts else None

            def align(bound: datetime | None) -> datetime | None:
                if bound is None:
                    return None
                if sample_tz is None:
                    return bound.replace(tzinfo=None)
                if bound.tzinfo is None:
                    return bound.replace(tzinfo=timezone.utc)
                return bound

            if scope == "video":
                start_b = align(start_dt_utc)
                end_b = align(end_dt_utc)
                start_i = bisect_left(sample_ts, start_b) if start_b is not None else 0
                end_i = bisect_right(sample_ts, end_b) if end_b is not None else len(sample_ts)

                sliced_samples = samples[start_i:end_i]
                chart_start = max(sample_ts[0], start_b) if start_b is not None else sample_ts[0]
                chart_end = min(sample_ts[-1], end_b) if end_b is not None else sample_ts[-1]
            else:  # "activity" mode (default)
                sliced_samples = samples
                if source_activity_ranges and src in source_activity_ranges:
                    raw_start, raw_end = source_activity_ranges[src]
                    chart_start = align(raw_start) or sample_ts[0]
                    chart_end = align(raw_end) or sample_ts[-1]
                else:
                    chart_start = sample_ts[0]
                    chart_end = sample_ts[-1]

            if len(sliced_samples) >= 2:
                chart_data[ind_key] = ChartHistory(
                    [s[1] for s in sliced_samples],
                    [s[0] for s in sliced_samples],
                    chart_start_dt=chart_start,
                    chart_end_dt=chart_end,
                    time_scope=scope,
                )
            elif sliced_samples:
                chart_data[ind_key] = ChartHistory(
                    [s[1] for s in sliced_samples],
                    [s[0] for s in sliced_samples],
                    chart_start_dt=chart_start,
                    chart_end_dt=chart_end,
                    time_scope=scope,
                )
            else:
                chart_data[ind_key] = ChartHistory([], [], chart_start_dt=chart_start, chart_end_dt=chart_end, time_scope=scope)
    return chart_data
