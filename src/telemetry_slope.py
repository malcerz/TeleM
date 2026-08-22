"""Causal, source-local derived grade/slope telemetry.

The public binding is ``slope`` and its unit is percent.  This module only
derives data; it deliberately does not know anything about indicators,
layouts, or rendering backends.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import deque
from datetime import datetime, timedelta
from typing import Iterable


DEFAULT_SLOPE_WINDOW_M = 20.0
DEFAULT_SLOPE_MAX_LOOKBACK_S = 10.0
DEFAULT_SLOPE_SMOOTHING_WINDOW_S = 2.0
DEFAULT_SLOPE_MAX_ABS_PERCENT = 100.0


def _naive_dt(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def align_slope_samples(
    distance_samples: Iterable[tuple[datetime, float]],
    altitude_samples: Iterable[tuple[datetime, float]],
) -> list[tuple[datetime, float | None, float | None]]:
    """Join altitude samples with the latest distance at or before each time.

    The join is intentionally causal.  A future distance sample cannot affect
    the slope emitted for an earlier altitude timestamp.
    """
    distances = sorted(
        [(_naive_dt(dt), _finite(value)) for dt, value in distance_samples],
        key=lambda item: item[0],
    )
    altitudes = sorted(
        [(_naive_dt(dt), _finite(value)) for dt, value in altitude_samples],
        key=lambda item: item[0],
    )
    result: list[tuple[datetime, float | None, float | None]] = []
    distance_index = 0
    latest_distance: float | None = None
    for timestamp, altitude in altitudes:
        while distance_index < len(distances) and distances[distance_index][0] <= timestamp:
            latest_distance = distances[distance_index][1]
            distance_index += 1
        result.append((timestamp, latest_distance, altitude))
    return result


def derive_slope_samples(
    samples: Iterable[tuple[datetime, float | None, float | None]],
    *,
    window_distance_m: float = DEFAULT_SLOPE_WINDOW_M,
    max_lookback_s: float = DEFAULT_SLOPE_MAX_LOOKBACK_S,
    smoothing_window_s: float = DEFAULT_SLOPE_SMOOTHING_WINDOW_S,
    max_abs_slope_percent: float = DEFAULT_SLOPE_MAX_ABS_PERCENT,
) -> list[tuple[datetime, float | None]]:
    """Derive a causal grade percentage from ``(time, distance, altitude)``.

    A valid value is ``100 * delta_altitude / delta_distance`` over a travelled
    distance window.  Before the first valid window, and after a timestamp gap
    or distance reset, the result is ``None``.  During a stop or a short period
    without enough new distance, the last valid value is held.  Invalid and
    non-finite values never enter the history and are never emitted.
    """
    window_distance_m = max(0.1, float(window_distance_m))
    max_lookback_s = max(0.1, float(max_lookback_s))
    smoothing_window_s = max(0.0, float(smoothing_window_s))
    max_abs_slope_percent = max(0.1, float(max_abs_slope_percent))

    ordered = sorted(
        [(_naive_dt(dt), _finite(distance), _finite(altitude)) for dt, distance, altitude in samples],
        key=lambda item: item[0],
    )
    if not ordered:
        return []

    # Only retain the amount of history that can still be selected as a
    # causal baseline.  The timestamp check remains explicit below because a
    # distance stop may otherwise leave old points in the deque.
    history: deque[tuple[datetime, float, float]] = deque()
    raw_values: list[tuple[datetime, float | None]] = []
    last_valid: float | None = None
    previous_seen_dt: datetime | None = None
    previous_distance: float | None = None

    for timestamp, distance, altitude in ordered:
        discontinuity = (
            previous_seen_dt is not None
            and (timestamp - previous_seen_dt).total_seconds() > max_lookback_s
        )
        if (
            not discontinuity
            and distance is not None
            and previous_distance is not None
            and distance < previous_distance - 1e-6
        ):
            discontinuity = True
        if discontinuity:
            history.clear()
            last_valid = None

        previous_seen_dt = timestamp
        if distance is not None:
            previous_distance = distance

        if distance is None or altitude is None:
            raw_values.append((timestamp, None if last_valid is None else last_valid))
            continue

        while history and (
            (timestamp - history[0][0]).total_seconds() > max_lookback_s
            or distance < history[0][1] - 1e-6
        ):
            history.popleft()

        candidate: float | None = None
        for base_timestamp, base_distance, base_altitude in reversed(history):
            distance_delta = distance - base_distance
            age_s = (timestamp - base_timestamp).total_seconds()
            if distance_delta >= window_distance_m and 0.0 < age_s <= max_lookback_s:
                candidate = 100.0 * (altitude - base_altitude) / distance_delta
                break

        if candidate is not None and math.isfinite(candidate):
            if abs(candidate) <= max_abs_slope_percent:
                last_valid = candidate
            # A rejected candidate does not replace the last valid value.
        history.append((timestamp, distance, altitude))
        raw_values.append((timestamp, None if last_valid is None else last_valid))

    if smoothing_window_s <= 0.0:
        return raw_values

    smoothed: list[tuple[datetime, float | None]] = []
    smoothing_history: deque[tuple[datetime, float]] = deque()
    for timestamp, value in raw_values:
        if value is None:
            smoothing_history.clear()
            smoothed.append((timestamp, None))
            continue
        cutoff = timestamp - timedelta(seconds=smoothing_window_s)
        while smoothing_history and smoothing_history[0][0] < cutoff:
            smoothing_history.popleft()
        smoothing_history.append((timestamp, value))
        smoothed.append((timestamp, sum(v for _, v in smoothing_history) / len(smoothing_history)))
    return smoothed


def derive_slope_from_streams(
    distance_samples: Iterable[tuple[datetime, float]],
    altitude_samples: Iterable[tuple[datetime, float]],
    **kwargs: float,
) -> list[tuple[datetime, float | None]]:
    """Derive slope from separate, source-local distance and altitude streams."""
    return derive_slope_samples(
        align_slope_samples(distance_samples, altitude_samples), **kwargs
    )


def interpolate_slope(
    samples: list[tuple[datetime, float | None]], target_dt: datetime
) -> float | None:
    """Return the latest slope at or before ``target_dt`` (causal STEP)."""
    if not samples:
        return None
    target = _naive_dt(target_dt)
    ordered = sorted((_naive_dt(dt), _finite(value)) for dt, value in samples)
    index = bisect_right([dt for dt, _ in ordered], target) - 1
    if index < 0:
        return None
    value = ordered[index][1]
    return value if value is None else float(value)
