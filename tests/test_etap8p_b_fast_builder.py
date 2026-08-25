"""
Unit and regression test suite for ETAP 8P-B: Fast PRECOMPUTED Telemetry Builder.
Validates:
1. STEP full parity (searchsorted side="right" - 1 matching bisect_right - 1)
2. Linear full parity (speed, distance, altitude matching interpolate_* functions)
3. Exact timestamp lookup contract
4. Duplicate timestamp handling (last duplicate in sequence)
5. Before-first range clamp contract
6. After-last range clamp contract
7. None vs real zero (0.0) contract
8. Strict source isolation (FIT -> FIT only, GPMF -> GPMF only, GPX -> GPX only)
9. Dynamic FIT indicators (solar, battery, cadence, heart_rate)
10. IMU accelerometer/gyroscope fields
11. Shared immutable chart series
12. Shared immutable GPS track
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
import pytest
import numpy as np

from src.telemetry_precompute import (
    build_telemetry_cache,
    _vectorize_step,
    _vectorize_linear_speed,
    _vectorize_linear_distance,
    _vectorize_linear_altitude,
    TelemetryFrameCache,
)
from src.indicators.frame_data import (
    prepare_overlay_frame_data,
    build_active_fit_field_plan,
)
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker


def _create_sample_dataset():
    base_dt = datetime(2026, 8, 19, 10, 0, 0)
    
    speed_samples = [(base_dt + timedelta(seconds=i), float(10 * (i + 1))) for i in range(5)]
    track_samples = [(base_dt + timedelta(seconds=i), float(100 * i)) for i in range(5)]
    alt_samples = [(base_dt + timedelta(seconds=i), float(200 + 10 * i)) for i in range(5)]
    iso_samples = [(base_dt + timedelta(seconds=i), 100 * (i + 1)) for i in range(5)]
    exposure_samples = [(base_dt + timedelta(seconds=i), 1000 * (i + 1)) for i in range(5)]
    temperature_samples = [(base_dt + timedelta(seconds=i), 20 + i) for i in range(5)]
    
    fit_data = {
        "cadence": [(base_dt + timedelta(seconds=i), 80 + i) for i in range(5)],
        "heart_rate": [(base_dt + timedelta(seconds=i), 140 + i) for i in range(5)],
        "solar_pct": [(base_dt + timedelta(seconds=i), 50.0 + i) for i in range(5)],
        "battery_pct": [(base_dt + timedelta(seconds=i), 90.0 - i) for i in range(5)],
        "power": [(base_dt + timedelta(seconds=i), 200 + 10 * i) for i in range(5)],
    }
    
    gps_track = [(50.0 + 0.001 * i, 20.0 + 0.001 * i) for i in range(5)]
    
    layout = {
        "indicators": {
            "speed_visual": {"enabled": True, "source": "gpmf"},
            "speed_text": {"enabled": True, "source": "gpmf"},
            "dist_visual": {"enabled": True, "source": "gpmf"},
            "dist_text": {"enabled": True, "source": "gpmf"},
            "alt_visual": {"enabled": True, "source": "gpmf"},
            "alt_text": {"enabled": True, "source": "gpmf"},
            "iso_text": {"enabled": True, "source": "gpmf"},
            "exposure_text": {"enabled": True, "source": "gpmf"},
            "temp_text": {"enabled": True, "source": "gpmf"},
            "fit_cadence_text": {"enabled": True, "source": "fit"},
            "fit_heart_rate_text": {"enabled": True, "source": "fit"},
            "fit_solar_pct_text": {"enabled": True, "source": "fit"},
            "fit_battery_pct_text": {"enabled": True, "source": "fit"},
            "fit_power_text": {"enabled": True, "source": "fit"},
        }
    }
    
    return {
        "base_dt": base_dt,
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temperature_samples": temperature_samples,
        "fit_data": fit_data,
        "gps_track": gps_track,
        "layout": layout,
    }


def test_fast_builder_step_full_parity():
    """Verify searchsorted side='right' - 1 gives exact step parity with bisect_right - 1."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    target_dts = [base_dt + timedelta(seconds=0.3 * i) for i in range(15)]
    target_ts = np.array([(dt - base_dt).total_seconds() for dt in target_dts], dtype=np.float64)
    
    samples = [(base_dt + timedelta(seconds=i), 100 * (i + 1)) for i in range(5)]
    
    from src.telemetry_extract import _interpolate_step
    ref_vals = [_interpolate_step(samples, dt) for dt in target_dts]
    fast_vals = _vectorize_step(samples, target_dts, target_ts, base_dt)
    
    assert fast_vals == ref_vals, "STEP interpolation mismatch!"


def test_fast_builder_linear_full_parity():
    """Verify vectorized linear interpolations match interpolate_speed/distance/altitude."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    target_dts = [base_dt + timedelta(seconds=0.3 * i) for i in range(15)]
    target_ts = np.array([(dt - base_dt).total_seconds() for dt in target_dts], dtype=np.float64)
    
    from src.telemetry_extract import interpolate_speed, interpolate_distance, interpolate_altitude
    ref_spd = [interpolate_speed(ds["speed_samples"], dt) for dt in target_dts]
    fast_spd = _vectorize_linear_speed(ds["speed_samples"], target_dts, target_ts, base_dt)
    for r, f in zip(ref_spd, fast_spd):
        assert abs(r - f) < 1e-6
        
    ref_dist = [interpolate_distance(ds["track_samples"], dt) for dt in target_dts]
    fast_dist = _vectorize_linear_distance(ds["track_samples"], target_dts, target_ts, base_dt)
    for r, f in zip(ref_dist, fast_dist):
        assert abs(r - f) < 1e-6
        
    ref_alt = [interpolate_altitude(ds["alt_samples"], dt) for dt in target_dts]
    fast_alt = _vectorize_linear_altitude(ds["alt_samples"], target_dts, target_ts, base_dt)
    for r, f in zip(ref_alt, fast_alt):
        assert abs(r - f) < 1e-6


def test_fast_builder_exact_timestamp():
    """Exact timestamp sample.timestamp == target_dt returns that exact sample."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    exact_dts = [base_dt + timedelta(seconds=i) for i in range(5)]
    target_ts = np.array([(dt - base_dt).total_seconds() for dt in exact_dts], dtype=np.float64)
    
    iso_fast = _vectorize_step(ds["iso_samples"], exact_dts, target_ts, base_dt)
    assert iso_fast == [100, 200, 300, 400, 500]


def test_fast_builder_duplicate_timestamp():
    """For duplicate timestamps, select the last sample in existing order."""
    base_dt = datetime(2026, 8, 19, 10, 0, 0)
    samples = [
        (base_dt, 10),
        (base_dt + timedelta(seconds=1), 20),
        (base_dt + timedelta(seconds=1), 99),  # duplicate
        (base_dt + timedelta(seconds=2), 30),
    ]
    target_dts = [base_dt + timedelta(seconds=1)]
    target_ts = np.array([1.0], dtype=np.float64)
    
    res = _vectorize_step(samples, target_dts, target_ts, base_dt)
    assert res == [99], "Must return last duplicate sample!"


def test_fast_builder_before_first():
    """Before first timestamp contract: STEP returns None, linear clamped according to contract."""
    base_dt = datetime(2026, 8, 19, 10, 0, 0)
    samples = [(base_dt + timedelta(seconds=5), 100.0)]
    
    target_dts = [base_dt + timedelta(seconds=1)]  # before first (t=1 < t=5)
    target_ts = np.array([1.0], dtype=np.float64)
    
    step_res = _vectorize_step(samples, target_dts, target_ts, base_dt)
    assert step_res == [None], "Before first for STEP must be None!"
    
    spd_res = _vectorize_linear_speed(samples, target_dts, target_ts, base_dt)
    assert spd_res == [0.0], "Before first for speed must be 0.0!"
    
    dist_res = _vectorize_linear_distance(samples, target_dts, target_ts, base_dt)
    assert dist_res == [0.0], "Before first for distance must be 0.0!"
    
    alt_res = _vectorize_linear_altitude(samples, target_dts, target_ts, base_dt)
    assert alt_res == [100.0], "Before first for altitude must be sample[0]!"


def test_fast_builder_after_last():
    """After last timestamp contract: STEP and linear clamp to sample[-1]."""
    base_dt = datetime(2026, 8, 19, 10, 0, 0)
    samples = [(base_dt, 50.0), (base_dt + timedelta(seconds=2), 100.0)]
    
    target_dts = [base_dt + timedelta(seconds=10)]  # after last (t=10 > t=2)
    target_ts = np.array([10.0], dtype=np.float64)
    
    step_res = _vectorize_step(samples, target_dts, target_ts, base_dt)
    assert step_res == [100.0]
    
    spd_res = _vectorize_linear_speed(samples, target_dts, target_ts, base_dt)
    assert spd_res == [100.0]


def test_fast_builder_none_zero():
    """Real zero returns 0.0, missing returns None."""
    base_dt = datetime(2026, 8, 19, 10, 0, 0)
    samples_zero = [(base_dt, 0.0)]
    samples_empty = []
    
    target_dts = [base_dt]
    target_ts = np.array([0.0], dtype=np.float64)
    
    res_zero = _vectorize_step(samples_zero, target_dts, target_ts, base_dt)
    assert res_zero == [0.0]
    
    res_empty = _vectorize_step(samples_empty, target_dts, target_ts, base_dt)
    assert res_empty == [None]


def test_fast_builder_strict_source():
    """Strict source isolation: missing source data yields None without fallback."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    
    # Layout configured for GPX source, but no GPX data loaded
    layout = {
        "indicators": {
            "speed_visual": {"enabled": True, "source": "gpx"},
            "fit_cadence_text": {"enabled": True, "source": "fit"},
        }
    }
    
    init_worker(
        video_width=3840, video_height=2160, font_path="assets/Roboto-Bold.ttf",
        layout=layout, field_samples=ds["fit_data"],
        fit_data=ds["fit_data"], gpx_speed_samples=[],
        start_dt_utc=base_dt, tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"], track_samples=ds["track_samples"], alt_samples=ds["alt_samples"],
    )
    
    fit_field_plan = build_active_fit_field_plan(layout, ds["fit_data"].keys())
    cache = build_telemetry_cache(
        layout=layout, base_dt=base_dt, tz_offset_hours=0.0, start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"], track_samples=ds["track_samples"], alt_samples=ds["alt_samples"],
        fit_data=ds["fit_data"], chart_data={}, resolve_cache_value=_resolve_cache_value,
        fit_field_plan=fit_field_plan, total_frames=10, target_fps=10.0,
    )
    
    # GPX speed was requested but empty -> must be None!
    rec = cache.lookup(0)
    assert rec["speed_value"] is None, "GPX speed must be None when no GPX data is present!"


def test_fast_builder_dynamic_fit():
    """Dynamic FIT indicators (solar, battery) are correctly cached per-frame."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    
    init_worker(
        video_width=3840, video_height=2160, font_path="assets/Roboto-Bold.ttf",
        layout=ds["layout"], field_samples=ds["fit_data"],
        fit_data=ds["fit_data"], start_dt_utc=base_dt, tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"], track_samples=ds["track_samples"], alt_samples=ds["alt_samples"],
    )
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    cache = build_telemetry_cache(
        layout=ds["layout"], base_dt=base_dt, tz_offset_hours=0.0, start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"], track_samples=ds["track_samples"], alt_samples=ds["alt_samples"],
        fit_data=ds["fit_data"], chart_data={}, resolve_cache_value=_resolve_cache_value,
        fit_field_plan=fit_field_plan, total_frames=5, target_fps=1.0,
    )
    
    for i in range(5):
        rec = cache.lookup(i)
        extra = rec["extra_indicators"]
        assert "fit_solar_pct_text" in extra
        assert extra["fit_solar_pct_text"][0] == 50.0 + i
        assert "fit_battery_pct_text" in extra
        assert extra["fit_battery_pct_text"][0] == 90.0 - i


def test_fast_builder_imu():
    """IMU fields are handled without error and cached properly."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    
    layout = {
        "indicators": {
            "accel_x_text": {"enabled": True, "source": "gpmf"},
            "gyro_z_text": {"enabled": True, "source": "gpmf"},
        }
    }
    
    field_samples = {
        "accel_x_samples": [(base_dt + timedelta(seconds=i), float(i)) for i in range(5)],
        "gyro_z_samples": [(base_dt + timedelta(seconds=i), float(i * 0.5)) for i in range(5)],
    }
    
    init_worker(
        video_width=3840, video_height=2160, font_path="assets/Roboto-Bold.ttf",
        layout=layout, field_samples=field_samples,
        start_dt_utc=base_dt, tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"], track_samples=ds["track_samples"], alt_samples=ds["alt_samples"],
    )
    
    cache = build_telemetry_cache(
        layout=layout, base_dt=base_dt, tz_offset_hours=0.0, start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"], track_samples=ds["track_samples"], alt_samples=ds["alt_samples"],
        fit_data={}, chart_data={}, resolve_cache_value=_resolve_cache_value,
        total_frames=5, target_fps=1.0,
    )
    
    for i in range(5):
        rec = cache.lookup(i)
        assert rec["extra_indicators"]["accel_x_text"][0] == float(i)
        assert rec["extra_indicators"]["gyro_z_text"][0] == float(i * 0.5)


def test_fast_builder_chart_shared():
    """Chart data dictionary is shared immutable across lookups."""
    ds = _create_sample_dataset()
    chart_data = {"cadence": [80.0, 85.0, 90.0]}
    
    cache = build_telemetry_cache(
        layout=ds["layout"], base_dt=ds["base_dt"], tz_offset_hours=0.0, start_dt_utc=ds["base_dt"],
        speed_samples=ds["speed_samples"], track_samples=ds["track_samples"], alt_samples=ds["alt_samples"],
        fit_data=ds["fit_data"], chart_data=chart_data, total_frames=10, target_fps=1.0,
    )
    
    rec0 = cache.lookup(0)
    rec9 = cache.lookup(9)
    assert rec0["chart_data"] is chart_data
    assert rec9["chart_data"] is chart_data


def test_fast_builder_gps_shared():
    """GPS track list is shared immutable across lookups."""
    ds = _create_sample_dataset()
    gps_track = [(50.0, 20.0), (50.1, 20.1)]
    
    cache = build_telemetry_cache(
        layout=ds["layout"], base_dt=ds["base_dt"], tz_offset_hours=0.0, start_dt_utc=ds["base_dt"],
        speed_samples=ds["speed_samples"], track_samples=ds["track_samples"], alt_samples=ds["alt_samples"],
        fit_data=ds["fit_data"], gps_track=gps_track, total_frames=10, target_fps=1.0,
    )
    
    rec0 = cache.lookup(0)
    rec9 = cache.lookup(9)
    assert rec0["gps_track"] is gps_track
    assert rec9["gps_track"] is gps_track
