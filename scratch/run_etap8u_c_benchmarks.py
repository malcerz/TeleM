"""
ETAP 8U-C Benchmark Runner:
3x DIRECT MAP ON vs 3x REAL MAP OFF on 1131 frames + 1x 5395 Full Material.
"""
import os
import sys
import json
import time
import math
import statistics
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
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

out_dir_8uc = root / "Raporty" / "etap8u_c_artifacts"
out_dir_8uc.mkdir(parents=True, exist_ok=True)

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

v_5395 = root / "Video" / "GX030120.MP4"
fit_5395 = root / "Video" / "Morning_Ride.fit"

def setup_telemetry(video_path: Path, fit_path: Path):
    json_path = video_path.with_suffix(".json")
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

def run_export(run_name, video_path, fit_path, frames, map_enabled=True, env_overrides=None, target_w=3840, target_h=2160):
    env = os.environ.copy()
    env["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    env["AMD_ABOVE_TEXT_CACHE"] = "1"
    env["AMD_ABOVE_MULTI_REGION"] = "1"
    env["AMD_FLUSH_MODE"] = "BATCHED"
    env["AMD_CPU_GPU_PIPELINE"] = "SYNC"
    env["AMD_MAP_GPU_PATH"] = "DIRECT_AUTO"
    env["AMD_NATIVE_PROFILING"] = "0"
    env["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
    if env_overrides:
        env.update(env_overrides)
        
    layout_file = root / "def_layout.json"
    layout = normalize_layout(layout_file, target_w, target_h)
    if not map_enabled:
        layout["indicators"]["track_map"]["enabled"] = False
    
    out_mp4 = out_dir_8uc / f"{run_name}.mp4"
    if out_mp4.exists():
        try: out_mp4.unlink()
        except Exception: pass
        
    old_env = {}
    for k, v in env.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v
        
    try:
        print(f"\n=======================================================", flush=True)
        print(f"BENCHMARK RUN: {run_name} ({frames}f, map_enabled={map_enabled}, {target_w}x{target_h})", flush=True)
        print(f"=======================================================", flush=True)
        tm = setup_telemetry(video_path, fit_path)
        duration_s = frames / 29.97
        t0 = time.perf_counter()
        
        ok = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(video_path)],
            output_file=str(out_mp4),
            duration_s=duration_s,
            video_width=target_w,
            video_height=target_h,
            start_dt_utc=tm.start_dt_utc,
            tz_offset_hours=2.0,
            speed_samples=tm.speed_samples or [],
            track_samples=tm.track_samples or [],
            alt_samples=tm.alt_samples or [],
            font_path="assets/Roboto-Bold.ttf",
            layout=layout,
            field_samples=tm.fit_data or {},
            iso_samples=tm.iso_samples,
            exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples,
            fit_data=tm.fit_data,
            gps_track=tm.get_gps_track_for_source("fit"),
        )
        wall_s = time.perf_counter() - t0
        
        profile_json = out_mp4.with_suffix(".mp4.amd_profile.json")
        prof_data = {}
        if profile_json.exists():
            with open(profile_json) as f:
                prof_data = json.load(f)
                
        return {
            "run_name": run_name,
            "ok": ok,
            "total_wall_s": wall_s,
            "frames": frames,
            "map_enabled": map_enabled,
            "profile": prof_data,
        }
    finally:
        for k, old_v in old_env.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v

def main():
    results = {}
    
    # 1. 3x 4K DIRECT MAP ON
    print("\n=== 1. 3x 4K DIRECT MAP ON ===")
    results["direct_map_on_3x"] = []
    for i in range(1, 4):
        r = run_export(f"etap8u_c_direct_run{i}", v_1131, fit_1131, 1131, map_enabled=True)
        results["direct_map_on_3x"].append(r)
        
    # 2. 3x 4K REAL MAP OFF (track_map disabled)
    print("\n=== 2. 3x 4K REAL MAP OFF ===")
    results["real_map_off_3x"] = []
    for i in range(1, 4):
        r = run_export(f"etap8u_c_map_off_run{i}", v_1131, fit_1131, 1131, map_enabled=False)
        results["real_map_off_3x"].append(r)
        
    # 3. Full 5395-Frame Run with DIRECT
    print("\n=== 3. FULL 5395-FRAME 4K RUN (DIRECT) ===")
    r_5395 = run_export("etap8u_c_full_5395", v_5395, fit_5395, 5395, map_enabled=True)
    results["full_5395"] = r_5395
    
    out_json = out_dir_8uc / "etap8u_c_benchmark_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nALL BENCHMARKS COMPLETE. RESULTS SAVED TO {out_json}")

if __name__ == "__main__":
    main()
