"""
Comprehensive Audit & Microbenchmark Suite for ETAP 8U-A: GPU Map Resample & Blend Deep Audit.
"""
import os
import sys
import json
import time
import math
import statistics
import numpy as np
from PIL import Image
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
from src.indicators.moving_map import render_map_working_image, _map_render_plan

out_dir_8u = root / "Raporty" / "etap8u_a_artifacts"
out_dir_8u.mkdir(parents=True, exist_ok=True)

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

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

def analyze_geometry_histogram(tm, frames=1131):
    print("\n=== 1. ANALYZING GEOMETRY & CONSECUTIVE FRAME CHANGES (1131 frames) ===")
    layout_file = root / "def_layout.json"
    layout_4k = normalize_layout(layout_file, 3840, 2160)
    layout_1080 = normalize_layout(layout_file, 1920, 1080)
    gps_track = tm.get_gps_track_for_source("fit")
    
    geo_stats = {"4k": {}, "1080p": {}}
    
    # 4K Geometry
    src_sizes = []
    dst_sizes = []
    diff_pixels = []
    consecutive_changed_pixels = []
    last_img_arr = None
    
    for f in range(frames):
        cur_pos = f / (frames - 1) if frames > 1 else 0.0
        img, dst_bbox = render_map_working_image(
            3840, 2160, layout_4k, "track_map", gps_track, current_position=cur_pos
        )
        if img is not None and dst_bbox is not None:
            sw, sh = img.size
            dx, dy, dw, dh = dst_bbox
            src_sizes.append((sw, sh))
            dst_sizes.append((dw, dh))
            diff_pixels.append((abs(sw - dw), abs(sh - dh)))
            
            arr = np.array(img)
            if last_img_arr is not None:
                diff = np.any(arr != last_img_arr, axis=2)
                changed_ratio = float(np.mean(diff))
                consecutive_changed_pixels.append(changed_ratio)
            last_img_arr = arr
            
    print(f"4K Source Sizes:      {set(src_sizes)}")
    print(f"4K Dst Sizes:         {set(dst_sizes)}")
    print(f"4K Size Diffs (px):   {set(diff_pixels)}")
    print(f"4K Consecutive Change Ratio: Mean={np.mean(consecutive_changed_pixels)*100:.2f}%, Median={np.median(consecutive_changed_pixels)*100:.2f}%, Min={np.min(consecutive_changed_pixels)*100:.2f}%, Max={np.max(consecutive_changed_pixels)*100:.2f}%")
    
    # 1080p Geometry
    src_sizes_1080 = []
    dst_sizes_1080 = []
    for f in range(frames):
        cur_pos = f / (frames - 1) if frames > 1 else 0.0
        img, dst_bbox = render_map_working_image(
            1920, 1080, layout_1080, "track_map", gps_track, current_position=cur_pos
        )
        if img is not None and dst_bbox is not None:
            sw, sh = img.size
            dx, dy, dw, dh = dst_bbox
            src_sizes_1080.append((sw, sh))
            dst_sizes_1080.append((dw, dh))
            
    print(f"1080p Source Sizes:   {set(src_sizes_1080)}")
    print(f"1080p Dst Sizes:      {set(dst_sizes_1080)}")
    
    return {
        "4k_src": list(set(src_sizes))[0] if src_sizes else None,
        "4k_dst": list(set(dst_sizes))[0] if dst_sizes else None,
        "1080p_src": list(set(src_sizes_1080))[0] if src_sizes_1080 else None,
        "1080p_dst": list(set(dst_sizes_1080))[0] if dst_sizes_1080 else None,
        "change_ratio_mean": float(np.mean(consecutive_changed_pixels)),
        "change_ratio_median": float(np.median(consecutive_changed_pixels)),
    }

def run_export_benchmark(run_name, video_path, fit_path, frames, env_overrides=None, target_w=3840, target_h=2160):
    env = os.environ.copy()
    env["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    env["AMD_ABOVE_TEXT_CACHE"] = "1"
    env["AMD_ABOVE_MULTI_REGION"] = "1"
    env["AMD_FLUSH_MODE"] = "BATCHED"
    env["AMD_CPU_GPU_PIPELINE"] = "SYNC"
    env["AMD_NATIVE_PROFILING"] = "0"
    env["AMD_GPU_TIMESTAMP_PROFILE"] = "1" # Profile GPU timestamps
    if env_overrides:
        env.update(env_overrides)
        
    layout_file = root / "def_layout.json"
    layout = normalize_layout(layout_file, target_w, target_h)
    
    out_mp4 = out_dir_8u / f"{run_name}.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
        
    old_env = {}
    for k, v in env.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v
        
    try:
        print(f"\nRUNNING BENCHMARK: {run_name} (map_path={os.getenv('AMD_MAP_PATH')}, map_filter={os.getenv('AMD_MAP_FILTER')}, {target_w}x{target_h})", flush=True)
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
            "profile": prof_data,
        }
    finally:
        for k, old_v in old_env.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v

def main():
    tm = setup_telemetry(v_1131, fit_1131)
    
    # 1. Geometry Histogram
    geo_results = analyze_geometry_histogram(tm, frames=1131)
    
    # 2. Benchmark Suite
    results = {"geometry": geo_results}
    
    # 3x 4K Baseline (SYNC, Lanczos)
    print("\n=== 2. FRESH 3x 4K BASELINE (LANCZOS) ===")
    results["baseline_lanczos_4k"] = []
    for i in range(1, 4):
        r = run_export_benchmark(f"etap8u_a_lanczos_run{i}", v_1131, fit_1131, 1131, env_overrides={"AMD_MAP_FILTER": "LANCZOS"})
        results["baseline_lanczos_4k"].append(r)
        
    # 1x 4K Bilinear
    print("\n=== 3. 4K BILINEAR FILTER RUN ===")
    r_bilinear = run_export_benchmark("etap8u_a_bilinear", v_1131, fit_1131, 1131, env_overrides={"AMD_MAP_FILTER": "BILINEAR"})
    results["bilinear_4k"] = r_bilinear
    
    # 1x 4K Catmull-Rom Bicubic
    print("\n=== 4. 4K BICUBIC FILTER RUN ===")
    r_bicubic = run_export_benchmark("etap8u_a_bicubic", v_1131, fit_1131, 1131, env_overrides={"AMD_MAP_FILTER": "BICUBIC"})
    results["bicubic_4k"] = r_bicubic
    
    # 1x 4K Map OFF Control
    print("\n=== 5. 4K MAP OFF CONTROL RUN ===")
    r_map_off = run_export_benchmark("etap8u_a_map_off", v_1131, fit_1131, 1131, env_overrides={"AMD_MAP_PATH": "CPU_REFERENCE"})
    results["map_off_4k"] = r_map_off
    
    # 1x 1080p Baseline
    print("\n=== 6. 1080p BASELINE RUN ===")
    r_1080 = run_export_benchmark("etap8u_a_1080p_lanczos", v_1131, fit_1131, 1131, env_overrides={"AMD_MAP_FILTER": "LANCZOS"}, target_w=1920, target_h=1080)
    results["1080p"] = r_1080
    
    summary_file = out_dir_8u / "etap8u_a_audit_results.json"
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n=== AUDIT RUNS SAVED TO {summary_file} ===")

if __name__ == "__main__":
    main()
