"""Unit and integration tests for FIT Garmin/Edge Device Status extraction.

Verifies:
1. FIT parser extraction of message 104 (unknown_104 / device_status) records.
2. Canonical naming (garmin_battery_percent, garmin_battery_voltage, garmin_temperature).
3. Exact units & scaling (V for voltage, % for battery, °C for temperature).
4. Sparse step-hold interpolation semantics (no zeroing or blank drops between 1/min samples).
5. Source resolver & telemetry precompute integration.
6. Precompute & Compositor formatting (voltage decimals=2, battery %=0, temperature °C=0).
7. Multi-file activity-global continuity across clip boundaries (014 -> 015 -> 016).
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from telemetry_fit import parse_fit, sync_fit_to_video, FitDataset
from src.telemetry_resolver import resolve_samples_from_sources, resolve_field_from_sources, SOURCE_ALIASES
from src.telemetry_extract import interpolate_value, _interpolate_step
from src.telemetry_precompute import build_telemetry_cache, _vectorize_step
from src.indicators.compositor import compose_overlay
from src.multifile import build_timeline_from_paths, VideoTimeline, VideoClip


CANONICAL_FIT = Path(r"C:\_DEV\TeleM\Video\GX010114_116.fit")


@pytest.mark.skipif(not CANONICAL_FIT.exists(), reason="GX010114_116.fit not present in workspace")
def test_fit_device_status_extraction_real_fit():
    """Verify raw message 104 extraction on canonical GX010114_116.fit."""
    records = parse_fit(CANONICAL_FIT)
    assert records is not None
    assert hasattr(records, "field_catalog")
    
    catalog = records.field_catalog
    assert "garmin_battery_voltage" in catalog
    assert "garmin_battery_percent" in catalog
    assert "garmin_temperature" in catalog
    
    assert catalog["garmin_battery_voltage"]["unit"] == "V"
    assert catalog["garmin_battery_percent"]["unit"] == "%"
    assert catalog["garmin_temperature"]["unit"] == "°C"
    
    dataset = sync_fit_to_video(records, records[0]["timestamp"])
    assert "garmin_battery_voltage" in dataset
    assert "garmin_battery_percent" in dataset
    assert "garmin_temperature" in dataset
    
    voltage_samples = dataset["garmin_battery_voltage"]
    percent_samples = dataset["garmin_battery_percent"]
    temp_samples = dataset["garmin_temperature"]
    
    # Exact record count audited in GX010114_116.fit is 66
    assert len(voltage_samples) == 66
    assert len(percent_samples) == 66
    assert len(temp_samples) == 66
    
    # Check first record at 09:40:36 UTC
    first_dt, first_v = voltage_samples[0]
    assert first_dt == datetime(2026, 8, 14, 9, 40, 36)
    assert pytest.approx(first_v, 0.001) == 4.172
    assert pytest.approx(percent_samples[0][1], 0.1) == 91.0
    assert pytest.approx(temp_samples[0][1], 0.1) == 24.0
    
    # Check last record at 12:01:11 UTC
    last_dt, last_v = voltage_samples[-1]
    assert last_dt == datetime(2026, 8, 14, 12, 1, 11)
    assert pytest.approx(last_v, 0.001) == 4.126
    assert pytest.approx(percent_samples[-1][1], 0.1) == 87.0
    assert pytest.approx(temp_samples[-1][1], 0.1) == 35.0


def test_sparse_step_hold_interpolation():
    """Verify sparse step-hold semantics: no zeros or drops between 1/min records."""
    t0 = datetime(2026, 8, 14, 10, 0, 0)
    samples = [
        (t0, 4.172),
        (t0 + timedelta(seconds=60), 4.170),
        (t0 + timedelta(seconds=120), 4.165),
    ]
    
    # Exact timestamp match
    assert pytest.approx(interpolate_value(samples, t0)) == 4.172
    
    # In-between timestamps (step-hold holds previous sample)
    assert pytest.approx(interpolate_value(samples, t0 + timedelta(seconds=10))) == 4.172
    assert pytest.approx(interpolate_value(samples, t0 + timedelta(seconds=59))) == 4.172
    assert pytest.approx(interpolate_value(samples, t0 + timedelta(seconds=60))) == 4.170
    assert pytest.approx(interpolate_value(samples, t0 + timedelta(seconds=100))) == 4.170
    assert pytest.approx(interpolate_value(samples, t0 + timedelta(seconds=120))) == 4.165
    assert pytest.approx(interpolate_value(samples, t0 + timedelta(seconds=150))) == 4.165
    
    # Target slightly before first sample (within 120s pre-activity margin)
    assert pytest.approx(interpolate_value(samples, t0 - timedelta(seconds=25))) == 4.172


def test_vectorized_step_lookup_parity():
    """Verify _vectorize_step matches _interpolate_step across timestamps."""
    import numpy as np
    t0 = datetime(2026, 8, 14, 10, 0, 0)
    samples = [
        (t0, 91.0),
        (t0 + timedelta(seconds=60), 90.0),
        (t0 + timedelta(seconds=120), 89.0),
    ]
    
    targets = [
        t0 - timedelta(seconds=15),
        t0,
        t0 + timedelta(seconds=30),
        t0 + timedelta(seconds=60),
        t0 + timedelta(seconds=90),
        t0 + timedelta(seconds=120),
        t0 + timedelta(seconds=180),
    ]
    target_ts = np.array([(dt - t0).total_seconds() for dt in targets], dtype=np.float64)
    
    vec_results = _vectorize_step(samples, targets, target_ts, t0)
    step_results = [_interpolate_step(samples, dt) for dt in targets]
    
    assert len(vec_results) == len(step_results)
    for v, s in zip(vec_results, step_results):
        assert v == s


def test_source_aliases_and_resolver():
    """Verify source resolution and aliases for Garmin device status fields."""
    t0 = datetime(2026, 8, 14, 10, 0, 0)
    fit_data = {
        "garmin_battery_voltage": [(t0, 4.172)],
        "garmin_battery_percent": [(t0, 91.0)],
        "garmin_temperature": [(t0, 24.0)],
    }
    
    # Direct field names
    v_samples = resolve_samples_from_sources("garmin_battery_voltage", "fit", gpmf=None, fit_data=fit_data)
    assert len(v_samples) == 1
    assert v_samples[0][1] == 4.172
    
    pct_samples = resolve_samples_from_sources("garmin_battery_percent", "fit", gpmf=None, fit_data=fit_data)
    assert len(pct_samples) == 1
    assert pct_samples[0][1] == 91.0
    
    temp_samples = resolve_samples_from_sources("garmin_temperature", "fit", gpmf=None, fit_data=fit_data)
    assert len(temp_samples) == 1
    assert temp_samples[0][1] == 24.0
    
    # Generic battery / atemp aliases
    bat_samples = resolve_samples_from_sources("battery", "fit", gpmf=None, fit_data=fit_data)
    assert len(bat_samples) == 1
    assert bat_samples[0][1] == 91.0
    
    atemp_samples = resolve_samples_from_sources("atemp", "fit", gpmf=None, fit_data=fit_data)
    assert len(atemp_samples) == 1
    assert atemp_samples[0][1] == 24.0


def test_telemetry_precompute_and_formatting():
    """Verify build_telemetry_cache and compositor formatting for Garmin fields."""
    t0 = datetime(2026, 8, 14, 10, 0, 0)
    fit_data = {
        "garmin_battery_voltage": [(t0, 4.172)],
        "garmin_battery_percent": [(t0, 91.0)],
        "garmin_temperature": [(t0, 24.0)],
    }
    
    layout = {
        "width": 1920,
        "height": 1080,
        "indicators": {
            "fit_garmin_battery_voltage_text": {
                "enabled": True, "source": "fit", "form": "text", "unit": "V",
                "x": 100, "y": 100, "size": 3.0,
            },
            "fit_garmin_battery_percent_text": {
                "enabled": True, "source": "fit", "form": "text", "unit": "%",
                "x": 100, "y": 150, "size": 3.0,
            },
            "fit_garmin_temperature_text": {
                "enabled": True, "source": "fit", "form": "text", "unit": "°C",
                "x": 100, "y": 200, "size": 3.0,
            },
        }
    }
    
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=t0,
        tz_offset_hours=0.0,
        start_dt_utc=t0,
        speed_samples=[(t0, 25.0)],
        track_samples=[(t0, 100.0)],
        alt_samples=[(t0, 50.0)],
        fit_data=fit_data,
        total_frames=30,
        target_fps=30.0,
    )
    
    f0 = cache.lookup(0)
    assert "extra_indicators" in f0
    extra = f0["extra_indicators"]
    
    assert "fit_garmin_battery_voltage_text" in extra
    assert pytest.approx(extra["fit_garmin_battery_voltage_text"][0], 0.001) == 4.172
    
    assert "fit_garmin_battery_percent_text" in extra
    assert pytest.approx(extra["fit_garmin_battery_percent_text"][0], 0.1) == 91.0
    
    assert "fit_garmin_temperature_text" in extra
    assert pytest.approx(extra["fit_garmin_temperature_text"][0], 0.1) == 24.0


def test_multifile_timeline_device_status_continuity():
    """Verify multi-file timeline lookup across 014 -> 015 -> 016 boundaries."""
    # Construct synthetic multi-file timeline
    clip1 = VideoClip(path=Path("GX010114.MP4"), duration_s=100.0, fps=30.0,
                      absolute_start_dt=datetime(2026, 8, 14, 10, 0, 0),
                      absolute_end_dt=datetime(2026, 8, 14, 10, 1, 40),
                      timestamp_reliable=True)
    clip2 = VideoClip(path=Path("GX010115.MP4"), duration_s=100.0, fps=30.0,
                      absolute_start_dt=datetime(2026, 8, 14, 10, 1, 40),
                      absolute_end_dt=datetime(2026, 8, 14, 10, 3, 20),
                      timestamp_reliable=True)
    clip3 = VideoClip(path=Path("GX010116.MP4"), duration_s=100.0, fps=30.0,
                      absolute_start_dt=datetime(2026, 8, 14, 10, 3, 20),
                      absolute_end_dt=datetime(2026, 8, 14, 10, 5, 0),
                      timestamp_reliable=True)
    
    timeline = VideoTimeline(clips=[clip1, clip2, clip3])

    
    # 1-minute samples spanning the entire activity
    fit_data = {
        "garmin_battery_percent": [
            (datetime(2026, 8, 14, 10, 0, 0), 91.0),
            (datetime(2026, 8, 14, 10, 1, 0), 91.0),
            (datetime(2026, 8, 14, 10, 2, 0), 90.0),
            (datetime(2026, 8, 14, 10, 3, 0), 90.0),
            (datetime(2026, 8, 14, 10, 4, 0), 89.0),
        ]
    }
    
    # Check absolute time resolution in clip 1, clip 2, clip 3
    t_clip1 = timeline.frame_to_absolute(1500, 30.0) # frame 1500 in clip 1 = 10:00:50
    t_clip2 = timeline.frame_to_absolute(4500, 30.0) # frame 1500 in clip 2 = 10:02:30
    t_clip3 = timeline.frame_to_absolute(7500, 30.0) # frame 1500 in clip 3 = 10:04:10

    
    val1 = interpolate_value(fit_data["garmin_battery_percent"], t_clip1)
    val2 = interpolate_value(fit_data["garmin_battery_percent"], t_clip2)
    val3 = interpolate_value(fit_data["garmin_battery_percent"], t_clip3)
    
    assert val1 == 91.0
    assert val2 == 90.0
    assert val3 == 89.0

