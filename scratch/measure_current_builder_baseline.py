"""
Measure current TelemetryFrameCache builder baseline for:
300, 900, 1131, 1800, 5395 frames on canonical dataset (GX030120.MP4 + Popoludniowa...fit)
and (GX020079.mp4 + Morning_Ride.fit).
"""
import os
import sys
import time
from pathlib import Path

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
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value
from src.indicators.frame_data import build_active_fit_field_plan

def setup_telemetry(video_name: str, fit_name: str):
    video_path = root / "Video" / video_name
    json_path = video_path.with_suffix(".json")
    fit_path = root / "Video" / fit_name
    
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
    return tm

def benchmark_dataset(ds_name: str, video_name: str, fit_name: str, frame_counts: list[int]):
    print(f"\n=======================================================", flush=True)
    print(f"MEASURING CURRENT BUILDER BASELINE: {ds_name}", flush=True)
    print(f"=======================================================", flush=True)
    
    tm = setup_telemetry(video_name, fit_name)
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    
    field_samples = tm.fit_data or {}
    from src.ffmpeg.worker_cache import init_worker
    init_worker(
        video_width=3840,
        video_height=2160,
        font_path="assets/Roboto-Bold.ttf",
        layout=layout,
        field_samples=field_samples,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples,
        gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples,
        gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples,
        gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2.0,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        target_fps=29.97,
    )
    
    fit_field_plan = build_active_fit_field_plan(layout, field_samples.keys())
    
    results = []
    print(f"{'Frames':>8} | {'Build Wall (ms)':>16} | {'Build Wall (s)':>14} | {'ms/frame':>10} | {'RAM (KiB)':>10}")
    print("-" * 70)
    
    for n in frame_counts:
        t0 = time.perf_counter()
        cache = build_telemetry_cache(
            layout=layout,
            base_dt=tm.start_dt_utc,
            tz_offset_hours=2.0,
            start_dt_utc=tm.start_dt_utc,
            speed_samples=tm.speed_samples or [],
            track_samples=tm.track_samples or [],
            alt_samples=tm.alt_samples or [],
            iso_samples=tm.iso_samples,
            exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples,
            gpx_speed_samples=tm.gpx_speed_samples,
            gpx_track_samples=tm.gpx_track_samples,
            gpx_alt_samples=tm.gpx_alt_samples,
            gpx_power_samples=tm.gpx_power_samples,
            gpx_atemp_samples=tm.gpx_atemp_samples,
            gpx_hr_samples=tm.gpx_hr_samples,
            gpx_cad_samples=tm.gpx_cad_samples,
            fit_data=tm.fit_data,
            gps_track=tm.get_gps_track_for_source("fit"),
            chart_data={},
            resolve_cache_value=_resolve_cache_value,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
            fit_field_plan=fit_field_plan,
            total_frames=n,
            target_fps=29.97,
        )
        elapsed_s = time.perf_counter() - t0
        elapsed_ms = elapsed_s * 1000.0
        ms_per_frame = elapsed_ms / n
        ram_kib = cache.memory_bytes / 1024.0
        print(f"{n:8d} | {elapsed_ms:16.2f} | {elapsed_s:14.3f} | {ms_per_frame:10.3f} | {ram_kib:10.1f}")
        results.append({
            "frames": n,
            "build_wall_ms": elapsed_ms,
            "build_wall_s": elapsed_s,
            "ms_per_frame": ms_per_frame,
            "ram_kib": ram_kib,
        })
    return results

def main():
    counts = [300, 900, 1131, 1800, 5395]
    res_complex = benchmark_dataset(
        "GX030120 + Solar/Battery FIT (Canonical Complex)",
        "GX030120.MP4",
        "Popoludniowa_jazda_na_rowerze_solar_battery.fit",
        counts
    )
    res_standard = benchmark_dataset(
        "GX020079 + Morning_Ride FIT (Standard 1131f)",
        "GX020079.mp4",
        "Morning_Ride.fit",
        counts
    )

if __name__ == "__main__":
    main()
