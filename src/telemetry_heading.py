"""GPS-derived course-over-ground heading.

The canonical ``heading`` value in TeleM is geographic GPS course over ground,
not magnetic heading, camera yaw, bicycle yaw, or device orientation.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import deque
from datetime import datetime
from typing import Any, Iterable


DEFAULT_MIN_DISTANCE_M = 5.0
DEFAULT_MAX_LOOKBACK_S = 5.0
DEFAULT_SPEED_THRESHOLD_KMH = 1.0
DEFAULT_SMOOTHING_WINDOW_S = 2.0
DEFAULT_MAX_SEGMENT_SPEED_KMH = 180.0


def _naive_dt(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def normalize_heading(degrees: float) -> float:
    """Normalize an angle to the canonical half-open range ``[0, 360)``."""
    value = float(degrees) % 360.0
    return 0.0 if abs(value) < 1e-12 or abs(value - 360.0) < 1e-12 else value


def circular_difference(a: float, b: float) -> float:
    """Return the shortest absolute angular difference in degrees."""
    return abs(((float(b) - float(a) + 180.0) % 360.0) - 180.0)


def circular_interpolate(a: float, b: float, fraction: float) -> float:
    """Interpolate angles along the shortest arc, including the 359→1 wrap."""
    delta = ((float(b) - float(a) + 180.0) % 360.0) - 180.0
    return normalize_heading(float(a) + max(0.0, min(1.0, fraction)) * delta)


def bearing_degrees(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Return geodetic GPS course over ground, 0°=north, 90°=east."""
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dlon = math.radians(float(lon2) - float(lon1))
    x = math.sin(dlon) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return normalize_heading(math.degrees(math.atan2(x, y)))


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6_371_000.0
    p1 = math.radians(a[0])
    p2 = math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    value = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return radius * 2.0 * math.atan2(math.sqrt(value), math.sqrt(1.0 - value))


def _valid_position(point: Any) -> bool:
    if not isinstance(point, (tuple, list)) or len(point) < 3:
        return False
    try:
        lat, lon = float(point[1]), float(point[2])
    except (TypeError, ValueError):
        return False
    return math.isfinite(lat) and math.isfinite(lon) and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _speed_at_or_before(
    speed_samples: list[tuple[datetime, float]], target: datetime
) -> float | None:
    if not speed_samples:
        return None
    target = _naive_dt(target)
    ordered = [(_naive_dt(dt), value) for dt, value in speed_samples if value is not None]
    ordered.sort(key=lambda item: item[0])
    if not ordered:
        return None
    times = [item[0] for item in ordered]
    index = bisect_right(times, target) - 1
    if index < 0:
        return None
    try:
        value = float(ordered[index][1])
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _circular_mean(values: Iterable[float]) -> float:
    angles = list(values)
    if not angles:
        raise ValueError("circular mean requires at least one value")
    x = sum(math.cos(math.radians(v)) for v in angles)
    y = sum(math.sin(math.radians(v)) for v in angles)
    if math.hypot(x, y) < 1e-12:
        return normalize_heading(angles[-1])
    return normalize_heading(math.degrees(math.atan2(y, x)))


def derive_heading_samples(
    gps_track: list[tuple[datetime, float, float]],
    speed_samples: list[tuple[datetime, float]] | None = None,
    *,
    min_distance_m: float = DEFAULT_MIN_DISTANCE_M,
    max_lookback_s: float = DEFAULT_MAX_LOOKBACK_S,
    speed_threshold_kmh: float = DEFAULT_SPEED_THRESHOLD_KMH,
    smoothing_window_s: float = DEFAULT_SMOOTHING_WINDOW_S,
    max_segment_speed_kmh: float = DEFAULT_MAX_SEGMENT_SPEED_KMH,
) -> list[tuple[datetime, float | None]]:
    """Build a causal, source-local GPS course-over-ground stream.

    Each point is compared with a previous point at least ``min_distance_m``
    away, bounded by ``max_lookback_s``. No point after the current timestamp
    participates in the derived value. Low-speed samples hold the last valid
    heading, while a gap or invalid jump inserts a ``None`` marker until a new
    valid baseline is established.
    """
    if not gps_track:
        return []
    min_distance_m = max(0.1, float(min_distance_m))
    max_lookback_s = max(0.1, float(max_lookback_s))
    speed_threshold_kmh = max(0.0, float(speed_threshold_kmh))
    smoothing_window_s = max(0.0, float(smoothing_window_s))
    max_segment_speed_kmh = max(1.0, float(max_segment_speed_kmh))

    points = []
    for raw in gps_track:
        if not _valid_position(raw):
            continue
        dt = _naive_dt(raw[0])
        if points and dt <= points[-1][0]:
            continue
        points.append((dt, float(raw[1]), float(raw[2])))
    if not points:
        return []

    ordered_speeds = sorted(
        [
            (_naive_dt(dt), value)
            for dt, value in (speed_samples or [])
            if value is not None
        ],
        key=lambda item: item[0],
    )
    speed_times = [dt for dt, _ in ordered_speeds]

    def speed_at_or_before(target: datetime) -> float | None:
        if not ordered_speeds:
            return None
        speed_index = bisect_right(speed_times, target) - 1
        if speed_index < 0:
            return None
        try:
            value = float(ordered_speeds[speed_index][1])
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    raw_values: list[tuple[datetime, float | None]] = []
    last_valid: float | None = None
    previous_contiguous = 0

    for index, current in enumerate(points):
        current_dt, current_lat, current_lon = current
        if index == 0:
            raw_values.append((current_dt, None))
            continue

        prior_dt, prior_lat, prior_lon = points[index - 1]
        direct_dt_s = (current_dt - prior_dt).total_seconds()
        direct_m = _haversine_m((prior_lat, prior_lon), (current_lat, current_lon))
        segment_speed = direct_m / direct_dt_s * 3.6 if direct_dt_s > 0 else float("inf")
        discontinuity = (
            direct_dt_s > max_lookback_s
            or not math.isfinite(segment_speed)
            or segment_speed > max_segment_speed_kmh
        )
        if discontinuity:
            previous_contiguous = index
            last_valid = None
            raw_values.append((current_dt, None))
            continue

        if previous_contiguous == index - 1:
            baseline_index = index - 1
            travelled_m = direct_m
        else:
            baseline_index = index - 1
            travelled_m = direct_m
        while baseline_index > previous_contiguous and travelled_m < min_distance_m:
            left = points[baseline_index - 1]
            right = points[baseline_index]
            dt_s = (right[0] - left[0]).total_seconds()
            segment_m = _haversine_m((left[1], left[2]), (right[1], right[2]))
            implied_kmh = segment_m / dt_s * 3.6 if dt_s > 0 else float("inf")
            if dt_s > max_lookback_s or implied_kmh > max_segment_speed_kmh:
                previous_contiguous = baseline_index
                travelled_m = 0.0
                break
            travelled_m += segment_m
            baseline_index -= 1

        speed = speed_at_or_before(current_dt)
        if speed is None:
            speed = segment_speed if math.isfinite(segment_speed) else 0.0
        if speed < speed_threshold_kmh or travelled_m < min_distance_m:
            raw_values.append((current_dt, last_valid))
            continue

        base = points[baseline_index]
        heading = bearing_degrees(base[1], base[2], current_lat, current_lon)
        last_valid = heading
        raw_values.append((current_dt, heading))

    if smoothing_window_s <= 0.0:
        return raw_values

    smoothed: list[tuple[datetime, float | None]] = []
    window: deque[tuple[datetime, float]] = deque()
    for dt, value in raw_values:
        if value is None:
            window.clear()
            smoothed.append((dt, None))
            continue
        window.append((dt, value))
        cutoff = dt.timestamp() - smoothing_window_s
        while window and window[0][0].timestamp() < cutoff:
            window.popleft()
        smoothed.append((dt, _circular_mean(item[1] for item in window)))
    return smoothed


def interpolate_heading(
    samples: list[tuple[datetime, float | None]], target_dt: datetime
) -> float | None:
    """Causally select/interpolate a heading stream using circular semantics."""
    if not samples:
        return None
    target = _naive_dt(target_dt)
    # Derived streams are emitted chronologically.  Use bisect directly so a
    # preview lookup is O(log n) and never re-sorts the full telemetry track.
    index = bisect_right(
        samples, target, key=lambda item: _naive_dt(item[0])
    ) - 1
    if index < 0 or samples[index][1] is None:
        return None
    current_dt = _naive_dt(samples[index][0])
    current = float(samples[index][1])
    if index + 1 >= len(samples) or samples[index + 1][1] is None:
        return normalize_heading(current)
    next_dt = _naive_dt(samples[index + 1][0])
    next_value = samples[index + 1][1]
    span = (next_dt - current_dt).total_seconds()
    if span <= 0 or target >= next_dt:
        return normalize_heading(current)
    fraction = (target - current_dt).total_seconds() / span
    return circular_interpolate(current, float(next_value), fraction)
