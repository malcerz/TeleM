"""Unit coverage for ETAP 8B GPS-derived course-over-ground heading."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from src.ffmpeg.worker_cache import init_worker
from src.telemetry_heading import (
    bearing_degrees,
    circular_difference,
    circular_interpolate,
    derive_heading_samples,
    interpolate_heading,
)
from src.telemetry_precompute import build_telemetry_cache
from src.telemetry_resolver import resolve_samples_from_sources


T0 = datetime(2024, 1, 1, 12, 0, 0)


def _east_point(index: int, metres: float = 6.0) -> tuple[datetime, float, float]:
    # At the equator one degree of longitude is approximately 111.2 km.
    return T0 + timedelta(seconds=index), 0.0, index * metres / 111_200.0


def _samples(points, speed: float = 10.0):
    return [(point[0], speed) for point in points]


def _value_at(samples, dt):
    return next(value for sample_dt, value in samples if sample_dt == dt)


@pytest.mark.parametrize(
    ("lat2", "lon2", "expected"),
    [(1.0, 0.0, 0.0), (0.0, 1.0, 90.0), (-1.0, 0.0, 180.0), (0.0, -1.0, 270.0)],
)
def test_geodetic_bearing_cardinals(lat2, lon2, expected):
    assert bearing_degrees(0.0, 0.0, lat2, lon2) == pytest.approx(expected, abs=0.01)


def test_circular_wrap_interpolation():
    assert circular_interpolate(359.0, 1.0, 0.5) == pytest.approx(0.0)
    assert circular_interpolate(1.0, 359.0, 0.5) == pytest.approx(0.0)
    samples = [(T0, 359.0), (T0 + timedelta(seconds=1), 1.0)]
    assert interpolate_heading(samples, T0 + timedelta(seconds=0.5)) == pytest.approx(0.0)
    assert circular_difference(359.0, 1.0) == pytest.approx(2.0)


def test_min_distance_filters_small_gps_jitter_then_updates():
    points = [_east_point(i, 2.0) for i in range(5)]
    result = derive_heading_samples(
        points, _samples(points), min_distance_m=5.0, smoothing_window_s=0.0
    )
    assert _value_at(result, points[1][0]) is None
    assert _value_at(result, points[2][0]) is None
    assert _value_at(result, points[3][0]) == pytest.approx(90.0, abs=0.5)


def test_low_speed_holds_last_valid_and_starts_as_none():
    points = [_east_point(i, 6.0) for i in range(5)]
    speeds = [(points[0][0], 0.0), (points[1][0], 10.0)] + [
        (points[i][0], 0.1) for i in range(2, len(points))
    ]
    result = derive_heading_samples(points, speeds, smoothing_window_s=0.0)
    assert _value_at(result, points[0][0]) is None
    assert _value_at(result, points[1][0]) == pytest.approx(90.0, abs=0.5)
    assert _value_at(result, points[2][0]) == pytest.approx(90.0, abs=0.5)


def test_no_future_samples_affect_current_heading():
    p0, p1 = _east_point(0, 6.0), _east_point(1, 6.0)
    p2 = (T0 + timedelta(seconds=2), 6.0 / 111_200.0, p1[2])
    speeds = [(p0[0], 10.0), (p1[0], 10.0), (p2[0], 10.0)]
    full = derive_heading_samples([p0, p1, p2], speeds, smoothing_window_s=0.0)
    prefix = derive_heading_samples([p0, p1], speeds[:2], smoothing_window_s=0.0)
    assert _value_at(full, p1[0]) == pytest.approx(_value_at(prefix, p1[0]), abs=0.01)


def test_gap_and_invalid_position_do_not_create_bridge_heading():
    p0, p1 = _east_point(0, 6.0), _east_point(1, 6.0)
    gap = (T0 + timedelta(seconds=10), 0.0, p1[2])
    invalid = (T0 + timedelta(seconds=11), None, None)
    p3 = (T0 + timedelta(seconds=12), 0.0, p1[2] + 6.0 / 111_200.0)
    points = [p0, p1, gap, invalid, p3]
    speeds = [(p[0], 10.0) for p in (p0, p1, gap, p3)]
    result = derive_heading_samples(points, speeds, smoothing_window_s=0.0)
    assert _value_at(result, gap[0]) is None
    assert _value_at(result, p3[0]) is not None


def test_source_isolation():
    gpmf = SimpleNamespace(heading_samples=[(T0, 90.0)])
    gpx = SimpleNamespace(gpx_heading_samples=[(T0, 180.0)])
    fit = {"heading": [(T0, 270.0)]}
    assert resolve_samples_from_sources("heading", "gpmf", gpmf=gpmf, gpx=gpx, fit_data=fit) == [(T0, 90.0)]
    assert resolve_samples_from_sources("heading", "fit", gpmf=gpmf, gpx=gpx, fit_data=fit) == [(T0, 270.0)]
    assert resolve_samples_from_sources("heading", "gpx", gpmf=gpmf, gpx=gpx, fit_data=fit) == [(T0, 180.0)]


def test_precomputed_heading_uses_circular_interpolation():
    heading = [(T0, 359.0), (T0 + timedelta(seconds=2), 1.0)]
    layout = {"indicators": {"heading_text": {"enabled": True, "source": "gpmf"}}}
    init_worker(
        640, 360, "", layout, {"heading_samples": heading},
        total_overlay_frames=3, target_fps=1.0,
    )
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=T0,
        tz_offset_hours=0.0,
        start_dt_utc=T0,
        speed_samples=[], track_samples=[], alt_samples=[],
        total_frames=3,
        target_fps=1.0,
        fit_field_plan={
            "active_fit_fields": [],
            "active_standard_resolve_fields": ["heading"],
        },
    )
    assert cache.lookup(1)["extra_indicators"]["heading_text"][0] == pytest.approx(0.0)
