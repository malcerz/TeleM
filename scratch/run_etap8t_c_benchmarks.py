"""
Benchmark & Diagnostics runner for ETAP 8T-C: Async Pipeline Correctness & Performance Reconciliation.
Executes:
1. Queue Depth A/B (depth 1, 2, 3 on 300 frames 4K)
2. Fair 3x SYNC (1131f 4K, Profiling OFF)
3. Fair 3x ASYNC (1131f 4K, Profiling OFF)
4. 1080p SYNC vs 1080p ASYNC (1131f)
5. Full 5395f Run (GX030120.MP4 4K) with exact frame accounting
"""
import os
import sys
import json
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
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

out_dir_8t = root / "Raporty" / "etap8t_c_artifacts"
out_dir_8t.mkdir(parents=True, exist_ok=True)

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
    env["AMD_NATIVE_PROFILING"] = "0"
    env["AMD_GPU_TIMESTAMP_PROFILE"] = "0"
    env["AMD_FLUSH_MODE"] = "BATCHED"
    env["AMD_CPU_GPU_PIPELINE"] = "SYNC"
    env["AMD_QUEUE_DEPTH"] = "2"
    if env_overrides:
        env.update(env_overrides)
        
    layout_file = root / "def_layout.json"
    layout = normalize_layout(layout_file, target_w, target_h)
    
    out_mp4 = out_dir_8t / f"{run_name}.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
        
    old_env = {}
    for k, v in env.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v
        
    try:
        print(f"\n=======================================================", flush=True)
        print(f"RUNNING: {run_name} (pipeline={os.getenv('AMD_CPU_GPU_PIPELINE')}, Q_DEPTH={os.getenv('AMD_QUEUE_DEPTH')}, TS={os.getenv('AMD_GPU_TIMESTAMP_PROFILE')}, {frames}f, {target_w}x{target_h})", flush=True)
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
        return res
    finally:
        for k, old_v in old_env.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v

def main():
    results = {}
    
    # Phase 1: Queue Depth Matrix (300 frames 4K, depth 1, 2, 3)
    print("\n--- PHASE 1: QUEUE DEPTH MATRIX (300 frames 4K) ---")
    results["q_depth"] = {}
    for d in (1, 2, 3):
        r = run_single_benchmark(f"etap8t_c_qdepth_{d}", v_1131, fit_1131, 300, env_overrides={"AMD_CPU_GPU_PIPELINE": "ASYNC", "AMD_QUEUE_DEPTH": str(d)})
        results["q_depth"][f"depth_{d}"] = r
        
    # Phase 2: Fair 3x SYNC (1131 frames 4K, Profiling OFF)
    print("\n--- PHASE 2: FAIR 3 x SYNC BASELINE (1131 frames 4K) ---")
    results["sync_1131"] = []
    for i in range(1, 4):
        r = run_single_benchmark(f"etap8t_c_sync_run{i}", v_1131, fit_1131, 1131, env_overrides={"AMD_CPU_GPU_PIPELINE": "SYNC", "AMD_GPU_TIMESTAMP_PROFILE": "0"})
        results["sync_1131"].append(r)
        
    # Phase 3: Fair 3x ASYNC (1131 frames 4K, Profiling OFF)
    print("\n--- PHASE 3: FAIR 3 x ASYNC (1131 frames 4K) ---")
    results["async_1131"] = []
    for i in range(1, 4):
        r = run_single_benchmark(f"etap8t_c_async_run{i}", v_1131, fit_1131, 1131, env_overrides={"AMD_CPU_GPU_PIPELINE": "ASYNC", "AMD_QUEUE_DEPTH": "2", "AMD_GPU_TIMESTAMP_PROFILE": "0"})
        results["async_1131"].append(r)
        
    # Phase 4: 1080p SYNC vs 1080p ASYNC
    print("\n--- PHASE 4: 1080p SYNC vs 1080p ASYNC (1131 frames 1920x1080) ---")
    r_1080_sync = run_single_benchmark("etap8t_c_1080p_sync", v_1131, fit_1131, 1131, env_overrides={"AMD_CPU_GPU_PIPELINE": "SYNC"}, target_w=1920, target_h=1080)
    r_1080_async = run_single_benchmark("etap8t_c_1080p_async", v_1131, fit_1131, 1131, env_overrides={"AMD_CPU_GPU_PIPELINE": "ASYNC", "AMD_QUEUE_DEPTH": "2"}, target_w=1920, target_h=1080)
    results["1080p"] = {"sync": r_1080_sync, "async": r_1080_async}
    
    # Phase 5: Full 5395 frames 4K ASYNC with flush drain
    print("\n--- PHASE 5: FULL MATERIAL (5395 frames 4K) WITH FLUSH DRAIN ---")
    r_5395 = run_single_benchmark("etap8t_c_full_5395", v_5395, fit_5395, 5395, env_overrides={"AMD_CPU_GPU_PIPELINE": "ASYNC", "AMD_QUEUE_DEPTH": "2"})
    results["full_5395"] = r_5395
    
    summary_file = out_dir_8t / "etap8t_c_benchmark_results.json"
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\n=== ALL ETAP 8T-C BENCHMARKS COMPLETE! Saved to {summary_file} ===")

if __name__ == "__main__":
    main()
