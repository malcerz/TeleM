import sys, os, time
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image
from datetime import datetime, timedelta
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor, interpolate_speed
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.command_builder import get_layout_hud_regions

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
n_frames = 1132
target_fps = 29.97

def test_source_isolation_and_zero():
    print("--- 1. TESTING SOURCE ISOLATION & ZERO SEMANTICS ---")
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    anchor_dt = find_gps_anchor(records)
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

    # Test A: FIT requested & available
    layout_a = {
        "version": 6, "global": {}, "custom_texts": [],
        "indicators": {
            "speed_visual": {"enabled": True, "source": "fit", "form": "gauge"},
            "fit_cadence_text": {"enabled": True, "source": "fit", "form": "text"},
        }
    }
    field_samples_a = {
        "start_dt_utc": anchor_dt,
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
    }
    init_worker(
        1920, 1080, "", layout_a, field_samples_a, None,
        None, None, None, None, None, None, None, None, None, None,
        fit_data, None, anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, 10, None, 0, None, None, False
    )
    cache_a = build_telemetry_cache(
        layout=layout_a, base_dt=anchor_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        fit_data=fit_data, total_frames=10, target_fps=target_fps,
        resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache")
    )
    frame0_a = cache_a.lookup(0)
    expected_fit_speed = interpolate_speed(fit_data["speed"], anchor_dt)
    assert abs(frame0_a["speed_value"] - expected_fit_speed) < 1e-6, f"Expected FIT speed {expected_fit_speed}, got {frame0_a['speed_value']}"
    print("  [TEST A PASSED] FIT requested and available -> correctly sourced from FIT.")

    # Test B: FIT requested but unavailable in FIT data while GPMF is available
    fit_data_no_speed = dict(fit_data)
    fit_data_no_speed["speed"] = [] # empty FIT speed
    init_worker(
        1920, 1080, "", layout_a, field_samples_a, None,
        None, None, None, None, None, None, None, None, None, None,
        fit_data_no_speed, None, anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, 10, None, 0, None, None, False
    )
    cache_b = build_telemetry_cache(
        layout=layout_a, base_dt=anchor_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        fit_data=fit_data_no_speed, total_frames=10, target_fps=target_fps,
        resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache")
    )
    frame0_b = cache_b.lookup(0)
    # When FIT is requested but empty, it must return None and NOT silently fallback to GPMF speed
    assert frame0_b["speed_value"] is None, f"Expected None for missing FIT speed, got {frame0_b['speed_value']}"
    print("  [TEST B PASSED] FIT requested but unavailable -> returned None without GPMF silent fallback.")

    # Test C: FIT value is 0.0
    fit_data_zero = dict(fit_data)
    fit_data_zero["cadence"] = [(fit_data["cadence"][0][0], 0.0)]
    init_worker(
        1920, 1080, "", layout_a, field_samples_a, None,
        None, None, None, None, None, None, None, None, None, None,
        fit_data_zero, None, anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, 10, None, 0, None, None, False
    )
    cache_c = build_telemetry_cache(
        layout=layout_a, base_dt=anchor_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        fit_data=fit_data_zero, total_frames=10, target_fps=target_fps,
        resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache")
    )
    frame0_c = cache_c.lookup(0)
    cad_val = frame0_c["extra_indicators"]["fit_cadence_text"][0]
    assert cad_val == 0.0 and cad_val is not None, f"Expected 0.0, got {cad_val}"
    print("  [TEST C PASSED] Value 0.0 is preserved as numeric 0.0 and not confused with None.")

    # Test D: Missing data semantics
    fit_data_empty = dict(fit_data)
    fit_data_empty["cadence"] = []
    init_worker(
        1920, 1080, "", layout_a, field_samples_a, None,
        None, None, None, None, None, None, None, None, None, None,
        fit_data_empty, None, anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, 10, None, 0, None, None, False
    )
    cache_d = build_telemetry_cache(
        layout=layout_a, base_dt=anchor_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        fit_data=fit_data_empty, total_frames=10, target_fps=target_fps,
        resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache")
    )
    frame0_d = cache_d.lookup(0)
    cad_val_d = frame0_d["extra_indicators"]["fit_cadence_text"][0]
    assert cad_val_d is None, f"Expected None for missing field, got {cad_val_d}"
    print("  [TEST D PASSED] Missing data correctly preserved as None.")

def test_pixel_parity():
    print("\n--- 2. TESTING PIXEL PARITY ON 0%, 25%, 50%, 75%, 100% ---")
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    anchor_dt = find_gps_anchor(records)
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

    field_samples = {
        "start_dt_utc": anchor_dt,
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temp_samples": temp_samples,
    }

    prod_layout = normalize_layout("def_layout.json", 1920, 1080)
    aw, ah, hud_regs = get_layout_hud_regions(prod_layout, 1920, 1080, max_regions=3)

    init_worker(
        1920, 1080, "", prod_layout, field_samples, None,
        iso_samples, exposure_samples, temp_samples,
        None, None, None, None, None, None, None,
        fit_data, fit_data.get("track"),
        anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, n_frames,
        None, 0, None, hud_regs, False,
    )
    chart_data = WORKER_CACHE.get("_precomputed_chart_data")
    _range_cache = WORKER_CACHE.get("_prep_cache")

    cache = build_telemetry_cache(
        layout=prod_layout, base_dt=anchor_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
        chart_data=chart_data, resolve_cache_value=_resolve_cache_value,
        _range_cache=_range_cache, total_frames=n_frames, target_fps=target_fps,
    )

    test_indices = [
        0,
        int(n_frames * 0.25),
        int(n_frames * 0.50),
        int(n_frames * 0.75),
        n_frames - 1,
    ]

    for idx in test_indices:
        pct = int(round(idx / (n_frames - 1) * 100))
        target_dt = anchor_dt + timedelta(seconds=idx / target_fps)

        # 1. NORMAL Reference path
        data_ref = prepare_overlay_frame_data(
            layout=prod_layout, target_dt=target_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
            speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
            iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
            fit_data=fit_data, gps_track=fit_data.get("track"),
            total_frames=n_frames, current_index=idx, chart_data=chart_data,
            resolve_cache_value=_resolve_cache_value, _range_cache=_range_cache,
        )
        img_ref = compose_overlay(
            1920, 1080, prod_layout, "",
            data_ref["date_text"], data_ref["time_text"],
            data_ref["speed_value"], data_ref["distance_m"], data_ref["max_distance_m"],
            data_ref["alt_value"], data_ref["min_alt"], data_ref["max_alt"],
            data_ref["iso_value"], data_ref["exposure_value"], data_ref["temp_value"],
            indicator_values=data_ref["indicator_values"],
            max_speed_kmh=data_ref["max_speed_kmh"],
            power_value=data_ref["power_value"],
            atemp_value=data_ref["atemp_value"],
            hr_value=data_ref["hr_value"],
            cad_value=data_ref["cad_value"],
            battery_value=data_ref["battery_value"],
            chart_data=data_ref["chart_data"],
            current_position=data_ref["current_position"],
            extra_indicators=data_ref["extra_indicators"],
            gps_track=data_ref["gps_track"],
            target_dt=data_ref["target_dt"],
            start_dt_utc=data_ref["start_dt_utc"],
            elapsed_seconds=data_ref["elapsed_seconds"],
            avg_speed_kmh=data_ref["avg_speed_kmh"],
        )

        # 2. PRECOMPUTED path
        data_pre = cache.lookup(idx)
        img_pre = compose_overlay(
            1920, 1080, prod_layout, "",
            data_pre["date_text"], data_pre["time_text"],
            data_pre["speed_value"], data_pre["distance_m"], data_pre["max_distance_m"],
            data_pre["alt_value"], data_pre["min_alt"], data_pre["max_alt"],
            data_pre["iso_value"], data_pre["exposure_value"], data_pre["temp_value"],
            indicator_values=data_pre["indicator_values"],
            max_speed_kmh=data_pre["max_speed_kmh"],
            power_value=data_pre["power_value"],
            atemp_value=data_pre["atemp_value"],
            hr_value=data_pre["hr_value"],
            cad_value=data_pre["cad_value"],
            battery_value=data_pre["battery_value"],
            chart_data=data_pre["chart_data"],
            current_position=data_pre["current_position"],
            extra_indicators=data_pre["extra_indicators"],
            gps_track=data_pre["gps_track"],
            target_dt=data_pre["target_dt"],
            start_dt_utc=data_pre["start_dt_utc"],
            elapsed_seconds=data_pre["elapsed_seconds"],
            avg_speed_kmh=data_pre["avg_speed_kmh"],
        )

        arr_ref = np.asarray(img_ref)
        arr_pre = np.asarray(img_pre)
        diff = np.abs(arr_ref.astype(np.int32) - arr_pre.astype(np.int32))
        max_diff = int(np.max(diff))
        diff_count = int(np.count_nonzero(diff))

        print(f"  Frame {idx:4d} ({pct:3d}%): max_diff = {max_diff}, diff_pixels = {diff_count}")
        assert max_diff == 0, f"Frame {idx} pixel mismatch: max_diff={max_diff}, diff_pixels={diff_count}"

    print("\n  ALL TEST FRAMES ARE BIT-EXACT PIXEL IDENTICAL (max_diff = 0, diff_pixels = 0)!")

if __name__ == "__main__":
    test_source_isolation_and_zero()
    test_pixel_parity()
