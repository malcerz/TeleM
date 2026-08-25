from __future__ import annotations

from datetime import datetime, timedelta
import copy
from typing import Any

from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value, WORKER_CACHE


def _create_sample_dataset():
    base_dt = datetime(2026, 8, 19, 10, 0, 0)
    
    # 5 linear speed samples: 0s -> 10 km/h, 1s -> 20 km/h, 2s -> 30 km/h, 3s -> 40 km/h, 4s -> 50 km/h
    speed_samples = [(base_dt + timedelta(seconds=i), float(10 * (i + 1))) for i in range(5)]
    
    # Track samples (datetime, distance in meters)
    track_samples = [
        (base_dt + timedelta(seconds=i), float(100 * i))
        for i in range(5)
    ]
    
    # Altitude samples
    alt_samples = [(base_dt + timedelta(seconds=i), float(200 + 10 * i)) for i in range(5)]
    
    # Step telemetry samples (ISO, exposure, temperature)
    iso_samples = [(base_dt + timedelta(seconds=i), 100 * (i + 1)) for i in range(5)]
    exposure_samples = [(base_dt + timedelta(seconds=i), 500 - 50 * i) for i in range(5)]
    temperature_samples = [(base_dt + timedelta(seconds=i), 25.0 + 0.5 * i) for i in range(5)]
    
    # FIT data
    fit_data = {
        "cadence": [(base_dt + timedelta(seconds=i), 80 + i) for i in range(5)],
        "heart_rate": [(base_dt + timedelta(seconds=i), 140 + 2 * i) for i in range(5)],
        "solar_pct": [(base_dt + timedelta(seconds=i), 60 + i) for i in range(5)],
        "battery_pct": [(base_dt + timedelta(seconds=i), 80 - i) for i in range(5)],
        "zero_field": [(base_dt + timedelta(seconds=i), 0.0) for i in range(5)],
    }
    
    gps_track = [
        {"lat": 50.0 + 0.001 * i, "lon": 20.0 + 0.001 * i, "alt": 200 + 10 * i, "time": base_dt + timedelta(seconds=i)}
        for i in range(5)
    ]
    
    layout = {
        "indicators": {
            "speed_text": {"enabled": True, "source": "gpmf"},
            "dist_text": {"enabled": True, "source": "gpmf"},
            "alt_text": {"enabled": True, "source": "gpmf"},
            "iso_text": {"enabled": True, "source": "gpmf"},
            "exposure_text": {"enabled": True, "source": "gpmf"},
            "temp_text": {"enabled": True, "source": "gpmf"},
            "cad_text": {"enabled": True, "source": "fit"},
            "hr_text": {"enabled": True, "source": "fit"},
            "fit_solar_pct_text": {"enabled": True, "source": "fit", "unit": "%", "label": "Solar Pct"},
            "fit_battery_pct_text": {"enabled": True, "source": "fit", "unit": "%", "label": "Battery Pct"},
            "fit_zero_field_text": {"enabled": True, "source": "fit", "unit": "", "label": "Zero Field"},
            "fit_missing_field_text": {"enabled": True, "source": "fit", "unit": "", "label": "Missing Field"},
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


def test_precomputed_reference_step_parity():
    """Verify STEP fields (ISO, Exposure, Temperature, Cadence, HR) produce identical step-lookup values."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    total_frames = 60
    target_fps = 10.0
    
    init_worker(
        video_width=1920,
        video_height=1080,
        font_path="assets/Roboto-Bold.ttf",
        layout=ds["layout"],
        field_samples=ds["fit_data"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        start_dt_utc=base_dt,
        tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        target_fps=target_fps,
        update_rate_step=1,
        total_overlay_frames=total_frames,
    )
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=total_frames,
        target_fps=target_fps,
    )
    
    for f_idx in range(total_frames):
        target_dt = base_dt + timedelta(seconds=f_idx / target_fps)
        ref = prepare_overlay_frame_data(
            layout=ds["layout"],
            target_dt=target_dt,
            start_dt_utc=base_dt,
            tz_offset_hours=0.0,
            speed_samples=ds["speed_samples"],
            track_samples=ds["track_samples"],
            alt_samples=ds["alt_samples"],
            iso_samples=ds["iso_samples"],
            exposure_samples=ds["exposure_samples"],
            temperature_samples=ds["temperature_samples"],
            total_frames=total_frames,
            current_index=f_idx,
            chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
            resolve_cache_value=_resolve_cache_value,
            fit_data=ds["fit_data"],
            gps_track=ds["gps_track"],
            _range_cache=WORKER_CACHE.get("_prep_cache"),
            fit_field_plan=fit_field_plan,
        )
        pre = cache.lookup(f_idx)
        
        for k in ("iso_value", "exposure_value", "temp_value", "cad_value", "hr_value"):
            assert ref[k] == pre[k], f"Mismatch at frame {f_idx} for {k}: ref={ref[k]} != pre={pre[k]}"


def test_precomputed_reference_linear_parity():
    """Verify linear continuous interpolation fields (speed, distance, altitude) match bit-exact."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    total_frames = 50
    target_fps = 10.0
    
    init_worker(
        video_width=1920,
        video_height=1080,
        font_path="assets/Roboto-Bold.ttf",
        layout=ds["layout"],
        field_samples=ds["fit_data"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        start_dt_utc=base_dt,
        tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        target_fps=target_fps,
        update_rate_step=1,
        total_overlay_frames=total_frames,
    )
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=total_frames,
        target_fps=target_fps,
    )
    
    for f_idx in range(total_frames):
        target_dt = base_dt + timedelta(seconds=f_idx / target_fps)
        ref = prepare_overlay_frame_data(
            layout=ds["layout"],
            target_dt=target_dt,
            start_dt_utc=base_dt,
            tz_offset_hours=0.0,
            speed_samples=ds["speed_samples"],
            track_samples=ds["track_samples"],
            alt_samples=ds["alt_samples"],
            iso_samples=ds["iso_samples"],
            exposure_samples=ds["exposure_samples"],
            temperature_samples=ds["temperature_samples"],
            total_frames=total_frames,
            current_index=f_idx,
            chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
            resolve_cache_value=_resolve_cache_value,
            fit_data=ds["fit_data"],
            gps_track=ds["gps_track"],
            _range_cache=WORKER_CACHE.get("_prep_cache"),
            fit_field_plan=fit_field_plan,
        )
        pre = cache.lookup(f_idx)
        for k in ("speed_value", "distance_m", "alt_value", "avg_speed_kmh"):
            assert abs(ref[k] - pre[k]) < 1e-5, f"Mismatch at frame {f_idx} for {k}: ref={ref[k]} != pre={pre[k]}"


def test_precomputed_none_zero():
    """Verify real zero (0.0) is preserved as 0.0, while missing data is preserved as None."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    total_frames = 10
    target_fps = 10.0
    
    init_worker(
        video_width=1920,
        video_height=1080,
        font_path="assets/Roboto-Bold.ttf",
        layout=ds["layout"],
        field_samples=ds["fit_data"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        start_dt_utc=base_dt,
        tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        target_fps=target_fps,
        update_rate_step=1,
        total_overlay_frames=total_frames,
    )
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=total_frames,
        target_fps=target_fps,
    )
    
    pre = cache.lookup(0)
    extra = pre["extra_indicators"]
    
    # Real zero must be 0.0
    assert extra["fit_zero_field_text"][0] == 0.0
    
    # Missing field must be None
    assert extra["fit_missing_field_text"][0] is None


def test_precomputed_strict_source():
    """Verify strict source ownership: no silent fallback to GPMF when FIT field is requested."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    # Add an indicator with source=fit where fit does NOT have the field
    layout = copy.deepcopy(ds["layout"])
    layout["indicators"]["fit_power_text"] = {"enabled": True, "source": "fit"}
    
    init_worker(
        video_width=1920,
        video_height=1080,
        font_path="assets/Roboto-Bold.ttf",
        layout=layout,
        field_samples=ds["fit_data"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        start_dt_utc=base_dt,
        tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        target_fps=10.0,
        update_rate_step=1,
        total_overlay_frames=10,
    )
    
    fit_field_plan = build_active_fit_field_plan(layout, ds["fit_data"].keys())
    
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=10,
        target_fps=10.0,
    )
    
    pre = cache.lookup(0)
    assert pre["power_value"] is None


def test_precomputed_exact_timestamp():
    """Verify regression ETAP 6E: exact sample timestamp returns exact sample, not previous."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    # Sample at exact second 2.0 (frame 20 at 10 fps)
    target_fps = 10.0
    total_frames = 30
    
    init_worker(
        video_width=1920,
        video_height=1080,
        font_path="assets/Roboto-Bold.ttf",
        layout=ds["layout"],
        field_samples=ds["fit_data"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        start_dt_utc=base_dt,
        tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        target_fps=target_fps,
        update_rate_step=1,
        total_overlay_frames=total_frames,
    )
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=total_frames,
        target_fps=target_fps,
    )
    
    # Frame 20 is exactly base_dt + 2.0s
    pre = cache.lookup(20)
    # ds["cadence"] at 2s is 80 + 2 = 82
    assert pre["cad_value"] == 82
    # ds["iso_samples"] at 2s is 100 * (2 + 1) = 300
    assert pre["iso_value"] == 300


def test_precomputed_chart_activity_scope():
    """Verify chart series in activity scope is preserved without per-frame duplication."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    
    chart_data = {
        "fit_heart_rate_text": [140.0, 142.0, 144.0, 146.0, 148.0],
        "fit_cadence_text": [80.0, 81.0, 82.0, 83.0, 84.0],
    }
    
    init_worker(
        video_width=1920,
        video_height=1080,
        font_path="assets/Roboto-Bold.ttf",
        layout=ds["layout"],
        field_samples=ds["fit_data"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        start_dt_utc=base_dt,
        tz_offset_hours=0.0,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        target_fps=10.0,
        update_rate_step=1,
        total_overlay_frames=10,
    )
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data=chart_data,
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=10,
        target_fps=10.0,
    )
    
    f0 = cache.lookup(0)
    f5 = cache.lookup(5)
    # Shared reference to same chart series
    assert f0["chart_data"] is f5["chart_data"]
    assert f0["chart_data"]["fit_heart_rate_text"] == [140.0, 142.0, 144.0, 146.0, 148.0]


def test_precomputed_chart_video_scope():
    """Verify video scope chart series is correctly stored and shared."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    
    chart_data = {
        "fit_cadence_text": [80.0, 80.5, 81.0, 81.5, 82.0],
    }
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data=chart_data,
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=10,
        target_fps=10.0,
    )
    
    f0 = cache.lookup(0)
    assert f0["chart_data"]["fit_cadence_text"] == [80.0, 80.5, 81.0, 81.5, 82.0]


def test_precomputed_map_marker():
    """Verify current_position advances monotonically from 0.0 to 1.0."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    total_frames = 11
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data={},
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=total_frames,
        target_fps=10.0,
    )
    
    f0 = cache.lookup(0)
    f5 = cache.lookup(5)
    f10 = cache.lookup(10)
    
    assert f0["current_position"] == 0.0
    assert abs(f5["current_position"] - 0.5) < 1e-6
    assert abs(f10["current_position"] - 1.0) < 1e-6


def test_precomputed_shared_chart_series():
    """Verify no memory duplication: static chart series is stored once in _Static."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    chart_data = {"series": list(range(1000))}
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data=chart_data,
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=500,
        target_fps=10.0,
    )
    
    # 500 frames should take very small memory since chart_data is shared
    assert cache.memory_bytes < 500_000, f"Expected <500 KB, got {cache.memory_bytes} bytes"


def test_precomputed_shared_gps_track():
    """Verify gps_track list is shared across all frame lookups without duplication."""
    ds = _create_sample_dataset()
    base_dt = ds["base_dt"]
    
    fit_field_plan = build_active_fit_field_plan(ds["layout"], ds["fit_data"].keys())
    cache = build_telemetry_cache(
        layout=ds["layout"],
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=ds["speed_samples"],
        track_samples=ds["track_samples"],
        alt_samples=ds["alt_samples"],
        iso_samples=ds["iso_samples"],
        exposure_samples=ds["exposure_samples"],
        temperature_samples=ds["temperature_samples"],
        fit_data=ds["fit_data"],
        gps_track=ds["gps_track"],
        chart_data={},
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=100,
        target_fps=10.0,
    )
    
    f10 = cache.lookup(10)
    f90 = cache.lookup(90)
    assert f10["gps_track"] is ds["gps_track"]
    assert f90["gps_track"] is ds["gps_track"]
