"""
Benchmark runner for ETAP 8S: D3D11 Flush Consolidation & GPU Command Batching.
Executes:
1. 3 x BEFORE (1131 frames 4K, AMD_FLUSH_MODE=LEGACY, TS ON)
2. 3 x AFTER  (1131 frames 4K, AMD_FLUSH_MODE=BATCHED, TS ON)
3. 1 x PROFILER OFF (1131 frames 4K, AMD_FLUSH_MODE=BATCHED, TS OFF)
4. 1 x 1080p (1131 frames 1920x1080, AMD_FLUSH_MODE=BATCHED, TS ON)
5. 1 x FULL 5395 (GX030120.MP4 4K, AMD_FLUSH_MODE=BATCHED, TS ON)
"""
import os
import sys
import json
import time
import shutil
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

out_dir_8s = root / "Raporty" / "etap8s_artifacts"
out_dir_8s.mkdir(parents=True, exist_ok=True)

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

v_5395 = root / "Video" / "GX030120.MP4"
fit_5395 = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"

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

def run_single_benchmark(run_name, video_path, fit_path, frames, env_overrides=None, target_w=3840, target_h=2160):
    env = os.environ.copy()
    env["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    env["AMD_ABOVE_TEXT_CACHE"] = "1"
    env["AMD_ABOVE_MULTI_REGION"] = "1"
    env["AMD_FRAME_ACCOUNT"] = "1"
    env["AMD_NATIVE_PROFILING"] = "1"
    env["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
    env["AMD_FLUSH_MODE"] = "BATCHED"
    if env_overrides:
        env.update(env_overrides)
        
    layout_file = root / "def_layout.json"
    layout = normalize_layout(layout_file, target_w, target_h)
    
    out_mp4 = out_dir_8s / f"{run_name}.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
        
    old_env = {}
    for k, v in env.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v
        
    try:
        print(f"\n=======================================================", flush=True)
        print(f"RUNNING: {run_name} (flush_mode={os.getenv('AMD_FLUSH_MODE')}, {frames} frames, {target_w}x{target_h})", flush=True)
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
                
        res = {
            "run_name": run_name,
            "ok": ok,
            "total_wall_s": wall_s,
            "frames": frames,
            "profile": prof_data,
        }
        
        csv_path = Path(str(out_mp4) + ".gpu_timeline.csv")
        if csv_path.exists():
            res["gpu_timeline_csv"] = str(csv_path)
            print(f"  [GPU TIMELINE] Generated GPU timeline at {csv_path}", flush=True)
            
        return res
    finally:
        for k, old_v in old_env.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v

def main():
    results = {}
    
    # 1. 3 x BEFORE (1131 frames, LEGACY 5-Flush)
    print("\n--- PHASE 1: 3 x BEFORE (1131 frames 4K, LEGACY 5-Flush, Profiler ON) ---")
    results["before_1131"] = []
    for i in range(1, 4):
        r = run_single_benchmark(f"etap8s_before_run{i}", v_1131, fit_1131, 1131, env_overrides={"AMD_FLUSH_MODE": "LEGACY"})
        results["before_1131"].append(r)
        
    # 2. 3 x AFTER (1131 frames, BATCHED 0 intermediate Flushes)
    print("\n--- PHASE 2: 3 x AFTER (1131 frames 4K, BATCHED, Profiler ON) ---")
    results["after_1131"] = []
    for i in range(1, 4):
        r = run_single_benchmark(f"etap8s_after_run{i}", v_1131, fit_1131, 1131, env_overrides={"AMD_FLUSH_MODE": "BATCHED"})
        results["after_1131"].append(r)
        
    # 3. 1 x Profiler OFF (Production Mode)
    print("\n--- PHASE 3: 1 x PROFILER OFF (1131 frames 4K, BATCHED, Profiler OFF) ---")
    r_ts_off = run_single_benchmark("etap8s_after_prof_off", v_1131, fit_1131, 1131, env_overrides={"AMD_FLUSH_MODE": "BATCHED", "AMD_GPU_TIMESTAMP_PROFILE": "0"})
    results["after_prof_off"] = r_ts_off
    
    # 4. 1 x 1080p Control
    print("\n--- PHASE 4: 1 x 1080p CONTROL (1131 frames 1920x1080, BATCHED, Profiler ON) ---")
    r_1080p = run_single_benchmark("etap8s_after_1080p", v_1131, fit_1131, 1131, env_overrides={"AMD_FLUSH_MODE": "BATCHED"}, target_w=1920, target_h=1080)
    results["after_1080p"] = r_1080p
    
    # 5. 1 x Full 5395 frames (GX030120.MP4, BATCHED)
    print("\n--- PHASE 5: 1 x FULL MATERIAL (5395 frames 4K, BATCHED, Profiler ON) ---")
    r_5395 = run_single_benchmark("etap8s_full_5395", v_5395, fit_5395, 5395, env_overrides={"AMD_FLUSH_MODE": "BATCHED"})
    results["full_5395"] = r_5395
    
    summary_file = out_dir_8s / "etap8s_benchmark_results.json"
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\n=== ALL ETAP 8S BENCHMARKS COMPLETE! Results saved to {summary_file} ===")

if __name__ == "__main__":
    main()
