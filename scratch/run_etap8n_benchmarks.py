"""
Benchmark script for ETAP 8N: Multi-Region CPU_ABOVE_MAP.
Runs 3 x BEFORE (single union bbox) and 3 x AFTER (multi-region).
Collects TRUE FPS, wall-clock timings, above breakdown, and pixel metrics.
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

video_path = root / "Video" / "GX030120.MP4"
json_path = root / "Video" / "GX030120.json"
fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
layout_path = root / "def_layout.json"

out_dir = root / "Raporty" / "etap8n_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

# 4K canonical layout
layout = normalize_layout(layout_path, 3840, 2160)

def setup_telemetry():
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

def run_single_benchmark(run_name: str, multi_region: bool, max_frames: int = 900):
    print(f"\n=======================================================", flush=True)
    print(f"STARTING RUN: {run_name} (multi_region={multi_region}, frames={max_frames})", flush=True)
    print(f"=======================================================", flush=True)
    
    os.environ["AMD_ABOVE_MULTI_REGION"] = "1" if multi_region else "0"
    os.environ["AMD_FRAME_ACCOUNT"] = "1"
    os.environ["AMD_NATIVE_PROFILING"] = "1"
    
    out_mp4 = out_dir / f"{run_name}.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
        
    tm = setup_telemetry()
    
    duration_s = max_frames / 29.97
    start_t = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(video_path)],
        output_file=str(out_mp4),
        duration_s=duration_s,
        video_width=3840,
        video_height=2160,
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
    wall_s = time.perf_counter() - start_t
    
    profile_json = out_mp4.with_suffix(".mp4.amd_profile.json")
    prof_data = {}
    if profile_json.exists():
        with open(profile_json) as f:
            prof_data = json.load(f)
            
    print(f"COMPLETED {run_name} in {wall_s:.3f}s -> ok={ok}", flush=True)
    return {
        "run_name": run_name,
        "multi_region": multi_region,
        "wall_s": wall_s,
        "ok": ok,
        "profile": prof_data,
    }

def main():
    max_frames = 900
    results = {"before": [], "after": []}
    
    # Run 3 x BEFORE
    for i in range(1, 4):
        res = run_single_benchmark(f"before_run{i}", multi_region=False, max_frames=max_frames)
        results["before"].append(res)
        
    # Run 3 x AFTER
    for i in range(1, 4):
        res = run_single_benchmark(f"after_run{i}", multi_region=True, max_frames=max_frames)
        results["after"].append(res)
        
    summary_path = out_dir / "etap8n_benchmark_summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nAll benchmark runs complete! Results saved to {summary_path}", flush=True)

if __name__ == "__main__":
    main()
