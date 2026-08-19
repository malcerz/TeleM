import sys
import json
from pathlib import Path
from datetime import timedelta

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.gui.layout_manager import normalize_layout
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.worker_cache import WORKER_CACHE

video_path = root / "Video" / "GX030120.MP4"
json_path = root / "Video" / "GX030120.json"
fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
layout_path = root / "def_layout.json"

layout = normalize_layout(layout_path, 3840, 2160)

tm = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
    get_rotation_meta_fn=get_rotation_from_metadata,
    get_container_rotation_fn=get_container_rotation,
    find_meta_json_fn=find_metadata_json,
    find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
    load_telemetry_fn=lambda *a: None,
    ensure_records_fn=ensure_records_list,
    load_json_fallback_fn=load_json_with_fallback,
    write_records_fn=lambda p, r: None,
    extract_samples_exiftool_fn=lambda f: [],
    extract_altitude_exiftool_fn=lambda f: [],
    extract_gps_track_fn=extract_gps_track,
    find_gps_anchor_fn=lambda r: None,
    smooth_values_fn=smooth_speed_values,
    extract_accelerometer_fn=extract_accelerometer_samples,
    extract_gyroscope_fn=extract_gyroscope_samples,
)
records = ensure_records_list(load_json_with_fallback(json_path))
tm.load_gpmf_records(records)
tm.load_fit(str(fit_path))

from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value, WORKER_CACHE

total_frames = 900
target_fps = 29.97
base_dt = tm.start_dt_utc
tz_offset_hours = 2.0

init_worker(
    video_width=3840,
    video_height=2160,
    font_path="assets/Roboto-Bold.ttf",
    layout=layout,
    field_samples=tm.fit_data or {},
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source("fit"),
    start_dt_utc=base_dt,
    tz_offset_hours=tz_offset_hours,
    speed_samples=tm.speed_samples or [],
    track_samples=tm.track_samples or [],
    alt_samples=tm.alt_samples or [],
    target_fps=target_fps,
    update_rate_step=1,
    total_overlay_frames=total_frames,
)

fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

cache = build_telemetry_cache(
    layout=layout,
    base_dt=base_dt,
    tz_offset_hours=tz_offset_hours,
    start_dt_utc=base_dt,
    speed_samples=tm.speed_samples or [],
    track_samples=tm.track_samples or [],
    alt_samples=tm.alt_samples or [],
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source("fit"),
    chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
    resolve_cache_value=_resolve_cache_value,
    _range_cache=WORKER_CACHE.get("_prep_cache"),
    fit_field_plan=fit_field_plan,
    total_frames=total_frames,
    target_fps=target_fps,
)

print(f"Cache build: {cache.build_ms:.2f} ms, frames: {cache.frames}, mem: {cache.memory_bytes/1024:.2f} KB")

# Test parity for all 900 frames
mismatches = 0
checked_keys = [
    "date_text", "time_text", "speed_value", "distance_m", "alt_value",
    "iso_value", "exposure_value", "temp_value", "power_value", "atemp_value",
    "hr_value", "cad_value", "battery_value", "current_position",
    "elapsed_seconds", "avg_speed_kmh", "target_dt"
]

test_frames = [0, int(14.3 * target_fps), int(total_frames * 0.25), int(total_frames * 0.5), int(total_frames * 0.75), total_frames - 1]

print("\n=== PER-FIELD PARITY CHECK AT KEY TIMESTAMPS ===")
for f_idx in test_frames:
    target_dt = base_dt + timedelta(seconds=f_idx / target_fps)
    ref = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        start_dt_utc=base_dt,
        tz_offset_hours=tz_offset_hours,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        total_frames=total_frames,
        current_index=f_idx,
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
    )
    pre = cache.lookup(f_idx)
    
    print(f"\nFrame {f_idx} (target_dt={target_dt.strftime('%H:%M:%S.%f')[:-3]}):")
    for k in checked_keys:
        v_ref = ref.get(k)
        v_pre = pre.get(k)
        match = (v_ref == v_pre) if not (isinstance(v_ref, float) and isinstance(v_pre, float)) else abs(v_ref - v_pre) < 1e-6
        status = "MATCH" if match else f"MISMATCH (ref={v_ref} != pre={v_pre})"
        if not match:
            mismatches += 1
            print(f"  {k:20}: {status}")
            
    # Check extra_indicators
    extra_ref = ref.get("extra_indicators", {})
    extra_pre = pre.get("extra_indicators", {})
    all_extra_keys = set(extra_ref.keys()) | set(extra_pre.keys())
    for ek in sorted(all_extra_keys):
        val_ref = extra_ref.get(ek)
        val_pre = extra_pre.get(ek)
        match = val_ref == val_pre
        if not match:
            mismatches += 1
            print(f"  extra[{ek}]: MISMATCH ref={val_ref} != pre={val_pre}")

print(f"\nChecked all {len(test_frames)} key frames. Total mismatches: {mismatches}")

# Full scan all 900 frames
total_all_mismatches = 0
for f_idx in range(total_frames):
    target_dt = base_dt + timedelta(seconds=f_idx / target_fps)
    ref = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        start_dt_utc=base_dt,
        tz_offset_hours=tz_offset_hours,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        total_frames=total_frames,
        current_index=f_idx,
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
    )
    pre = cache.lookup(f_idx)
    for k in checked_keys:
        v_ref = ref.get(k)
        v_pre = pre.get(k)
        match = (v_ref == v_pre) if not (isinstance(v_ref, float) and isinstance(v_pre, float)) else abs(v_ref - v_pre) < 1e-6
        if not match:
            total_all_mismatches += 1
            
    extra_ref = ref.get("extra_indicators", {})
    extra_pre = pre.get("extra_indicators", {})
    for ek in set(extra_ref.keys()) | set(extra_pre.keys()):
        if extra_ref.get(ek) != extra_pre.get(ek):
            total_all_mismatches += 1

print(f"FULL 900-FRAME SCAN: Total mismatches across all fields: {total_all_mismatches}")
