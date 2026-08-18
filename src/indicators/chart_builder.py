"""Chart data builder — pre-compute chart history for all chart-type indicators.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

from bisect import bisect_right, bisect_left
from datetime import datetime, timezone
from typing import Any, Callable


class ChartHistory(list[float]):
    """Values plus the immutable timestamps used to build the history.

    It remains a normal list for existing renderers and callers, while the
    shared frame-data path can clip it by absolute telemetry time without
    scanning or copying the complete source series on every frame.
    """

    __slots__ = ("timestamps",)

    def __init__(self, values: list[float], timestamps: list[datetime]):
        super().__init__(values)
        self.timestamps = tuple(timestamps)


def clip_chart_data(
    chart_data: dict[str, list[float]],
    target_dt: datetime | None,
    history_start: datetime | None = None,
) -> dict[str, list[float]]:
    """Return a timestamp-bounded, non-mutating view of chart histories.

    The lower bound preserves the existing video-visible/source-visible start
    contract.  Plain lists remain untouched for compatibility with external
    callers that do not provide timestamp metadata.
    """
    if target_dt is None:
        return chart_data

    clipped: dict[str, list[float]] = {}
    for key, values in chart_data.items():
        timestamps = getattr(values, "timestamps", None)
        if not timestamps:
            clipped[key] = values
            continue
        # FIT/GPMF can arrive as naive UTC datetimes while the video anchor is
        # timezone-aware.  Compare in the timestamp series' representation;
        # this does not alter or rewrite stored sample timestamps.
        sample_tz = timestamps[0].tzinfo
        def align(bound: datetime | None) -> datetime | None:
            if bound is None:
                return None
            if sample_tz is None:
                return bound.replace(tzinfo=None)
            if bound.tzinfo is None:
                return bound.replace(tzinfo=timezone.utc)
            return bound

        start_bound = align(history_start)
        end_bound = align(target_dt)
        start = bisect_left(timestamps, start_bound) if start_bound is not None else 0
        end = bisect_right(timestamps, end_bound)
        if end <= start:
            clipped[key] = ChartHistory([], [])
        else:
            clipped[key] = ChartHistory(
                list(values[start:end]), list(timestamps[start:end])
            )
    return clipped


def build_chart_data(
    layout: dict[str, Any],
    get_samples_fn: Callable[[str], tuple[list, list, list]],
    resolve_samples_fn: Callable[[str, str, str | None], list],
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
            vals = [v for _, v in resolve_samples_fn("power", src, ind_key)]
        elif "hr" in ind_key:
            vals = [v for _, v in resolve_samples_fn("hr", src, ind_key)]
        elif "cad" in ind_key:
            vals = [v for _, v in resolve_samples_fn("cad", src, ind_key)]
        elif "atemp" in ind_key:
            vals = [v for _, v in resolve_samples_fn("atemp", src, ind_key)]
        elif "battery" in ind_key:
            vals = [v for _, v in resolve_samples_fn("battery", src, ind_key)]
        elif "iso" in ind_key:
            vals = [v for _, v in resolve_samples_fn("iso", src, ind_key)]
        elif "exposure" in ind_key:
            vals = [v for _, v in resolve_samples_fn("exposure", src, ind_key)]
        elif "temp" in ind_key and "atemp" not in ind_key:
            vals = [v for _, v in resolve_samples_fn("temperature", src, ind_key)]
        elif ind_key in {
            "accel_x_text", "accel_y_text", "accel_z_text", "accel_magnitude_text",
            "gyro_x_text", "gyro_y_text", "gyro_z_text", "gyro_magnitude_text",
        }:
            vals = [v for _, v in resolve_samples_fn(ind_key[:-5], src, ind_key)]
        else:
            # Dla kluczy typu fit_{field_name}_text — wyciągnij field_name
            # i rozwiąż przez resolve_samples_fn
            if ind_key.startswith("fit_") and ind_key.endswith("_text"):
                field_name = ind_key[4:-5]
                vals = [v for _, v in resolve_samples_fn(field_name, "fit", ind_key)]
            else:
                vals = []
        if vals and len(vals) >= 2:
            # Keep timestamps beside the list values.  The list-compatible
            # return type preserves the public chart renderer contract.
            if "speed" in ind_key:
                samples = get_samples_fn(src)[0]
            elif "dist" in ind_key:
                samples = get_samples_fn(src)[1]
            elif "alt" in ind_key:
                samples = get_samples_fn(src)[2]
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
            elif ind_key.startswith("fit_") and ind_key.endswith("_text"):
                samples = resolve_samples_fn(ind_key[4:-5], "fit", ind_key)
            else:
                samples = []
            chart_data[ind_key] = ChartHistory(
                list(vals), [sample[0] for sample in samples[:len(vals)]]
            )
    return chart_data
