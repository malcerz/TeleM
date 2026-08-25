from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.ffmpeg.worker_cache import (
    WORKER_CACHE,
    _resolve_cache_value,
    init_worker,
)
from src.indicators.frame_data import build_active_fit_field_plan, prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.telemetry_resolver import resolve_samples_from_sources
from src.telemetry_slope import (
    align_slope_samples,
    derive_slope_from_streams,
    derive_slope_samples,
    interpolate_slope,
)


T0 = datetime(2026, 1, 1, 12, 0, 0)


def _times(values):
    return [T0 + timedelta(seconds=i) for i in range(len(values))]


def _stream(distance_values, altitude_values):
    return list(zip(_times(distance_values), distance_values)), list(
        zip(_times(altitude_values), altitude_values)
    )


def test_slope_uses_percent_geometry_and_holds_before_next_window():
    distance, altitude = _stream([0, 10, 20, 30, 40], [100, 101, 102, 103, 104])
    result = derive_slope_from_streams(
        distance, altitude, smoothing_window_s=0
    )
    assert result[0][1] is None
    assert result[1][1] is None
    assert result[2][1] == pytest.approx(10.0)
    assert result[3][1] == pytest.approx(10.0)
    assert result[4][1] == pytest.approx(10.0)


def test_slope_is_causal_and_future_samples_do_not_change_prefix():
    prefix = [
        (T0, 0.0, 0.0),
        (T0 + timedelta(seconds=1), 10.0, 1.0),
        (T0 + timedelta(seconds=2), 20.0, 2.0),
    ]
    extended = prefix + [(T0 + timedelta(seconds=3), 30.0, 100.0)]
    a = derive_slope_samples(prefix, smoothing_window_s=0)
    b = derive_slope_samples(extended, smoothing_window_s=0)
    assert b[: len(a)] == a
    assert interpolate_slope(b, T0 + timedelta(seconds=2, microseconds=500)) == pytest.approx(10.0)


def test_slope_holds_during_stop_but_rebuilds_after_gap():
    samples = [
        (T0, 0.0, 0.0),
        (T0 + timedelta(seconds=1), 20.0, 2.0),
        (T0 + timedelta(seconds=2), 20.0, 2.0),
        (T0 + timedelta(seconds=3), 20.0, 2.0),
        (T0 + timedelta(seconds=20), 20.0, 2.0),
        (T0 + timedelta(seconds=21), 40.0, 0.0),
        (T0 + timedelta(seconds=22), 60.0, 2.0),
    ]
    result = derive_slope_samples(samples, smoothing_window_s=0)
    assert result[1][1] == pytest.approx(10.0)
    assert result[2][1] == pytest.approx(10.0)
    assert result[3][1] == pytest.approx(10.0)
    assert result[4][1] is None
    assert result[5][1] == pytest.approx(-10.0)
    assert result[6][1] == pytest.approx(10.0)


def test_slope_resets_on_distance_reset_and_rejects_nonfinite_or_extreme_values():
    samples = [
        (T0, 0.0, 0.0),
        (T0 + timedelta(seconds=1), 20.0, 2.0),
        (T0 + timedelta(seconds=2), 5.0, 1000.0),
        (T0 + timedelta(seconds=3), 25.0, 1002.0),
        (T0 + timedelta(seconds=4), 45.0, 1004.0),
        (T0 + timedelta(seconds=5), 65.0, float("nan")),
    ]
    result = derive_slope_samples(samples, smoothing_window_s=0)
    assert result[1][1] == pytest.approx(10.0)
    assert result[2][1] is None
    assert result[3][1] == pytest.approx(10.0)
    assert result[4][1] == pytest.approx(10.0)
    assert result[5][1] == pytest.approx(10.0)
    assert all(value is None or value == pytest.approx(value) for _, value in result)


def test_alignment_and_source_resolution_are_source_local():
    gpmf_distance, gpmf_altitude = _stream([0, 20, 40], [0, 2, 4])
    aligned = align_slope_samples(gpmf_distance, gpmf_altitude)
    assert aligned[0][1:] == (0.0, 0.0)
    gpmf_slope = derive_slope_samples(aligned, smoothing_window_s=0)
    gpx_slope = [(T0, None), (T0 + timedelta(seconds=1), 3.0)]
    gpmf = SimpleNamespace(slope_samples=gpmf_slope)
    gpx = SimpleNamespace(gpx_slope_samples=gpx_slope)
    assert resolve_samples_from_sources("slope", "gpmf", gpmf=gpmf, gpx=gpx) == gpmf_slope
    assert resolve_samples_from_sources("slope", "gpx", gpmf=gpmf, gpx=gpx) == gpx_slope
    assert resolve_samples_from_sources("slope", "fit", gpmf=gpmf, fit_data={"slope": [(T0, 7.0)]}, gpx=gpx) == [(T0, 7.0)]


def test_slope_binding_reaches_reference_and_precomputed_cache_without_renderer():
    slope = [(T0, None), (T0 + timedelta(seconds=1), 8.0)]
    layout = {"indicators": {"slope_text": {"enabled": True, "source": "gpmf", "unit": "%", "label": "Slope"}}}
    plan = build_active_fit_field_plan(layout, [])
    assert plan["active_standard_resolve_fields"] == ["slope"]

    init_worker(
        640, 360, "", layout,
        {"slope_samples": slope},
        speed_samples=[], track_samples=[], alt_samples=[],
        target_fps=1.0, total_overlay_frames=3,
    )
    cache = build_telemetry_cache(
        layout=layout, base_dt=T0, tz_offset_hours=0.0,
        start_dt_utc=T0, speed_samples=[], track_samples=[], alt_samples=[],
        fit_field_plan=plan, total_frames=3, target_fps=1.0,
        resolve_cache_value=_resolve_cache_value,
    )
    assert cache.lookup(0)["extra_indicators"]["slope_text"][0] is None
    assert cache.lookup(1)["extra_indicators"]["slope_text"][0] == pytest.approx(8.0)

    prepared = prepare_overlay_frame_data(
        layout=layout, target_dt=T0 + timedelta(seconds=1),
        tz_offset_hours=0.0, start_dt_utc=T0,
        speed_samples=[], track_samples=[], alt_samples=[],
        fit_field_plan=plan, resolve_cache_value=_resolve_cache_value,
    )
    assert prepared["extra_indicators"]["slope_text"][0] == pytest.approx(8.0)
