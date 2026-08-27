import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import (
    get_rotation_from_metadata,
    load_json_with_fallback,
    ensure_records_list,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

OUT_DIR = Path("scratch/etap3a_bench")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def execute_run(tag: str, video_path: Path, fit_path: Path, layout_file: str, frames: int, env_overrides: dict):
    # Set environment
    env_clean = {
        "AMD_NATIVE_DIAGNOSTICS": "0",
        "AMD_NATIVE_PROFILING": "0",
        "AMD_GPU_TIMESTAMP_PROFILE": "0",
        "AMD_NATIVE_FRAME_ACCOUNTING": "0",
        "AMD_AMF_MODE": "ENCODE",
        "AMD_GPU_MAP_ROTATE": "1",
        "AMD_CHART_PATH": "GPU_SPLIT",
        "AMD_AFTER_MAP_GAUGE_GPU": "1",
        "AMD_LEAN_GPU": "0",
    }
    env_clean.update(env_overrides)
    for k, v in env_clean.items():
        os.environ[k] = str(v)

    layout = json.load(open(layout_file, encoding="utf-8"))

    tm = TelemetryDataManager()
    processed = read_processed_cache(video_path)
    if processed is not None:
        apply_processed_cache(tm, processed)
    else:
        tm.load_gpmf_from_exiftool(video_path)

    records = ensure_records_list(
        load_json_with_fallback(video_path.with_suffix(".json"))
    )
    rotation_degrees = get_rotation_from_metadata(records)
    fit_ok = tm.load_fit(video_path, start_dt=tm.start_dt_utc, manual_path=fit_path)

    field_samples = {
        "speed_samples": tm.speed_samples,
        "track_samples": tm.track_samples,
        "alt_samples": tm.alt_samples,
        "heading_samples": tm.heading_samples,
        "gpx_heading_samples": tm.gpx_heading_samples,
        "slope_samples": tm.slope_samples,
        "gpx_slope_samples": tm.gpx_slope_samples,
        "iso_samples": tm.iso_samples,
        "exposure_samples": tm.exposure_samples,
        "temperature_samples": tm.temperature_samples,
        "accel_x_samples": tm.accel_x_samples,
        "accel_y_samples": tm.accel_y_samples,
        "accel_z_samples": tm.accel_z_samples,
        "accel_magnitude_samples": tm.accel_magnitude_samples,
        "gyro_x_samples": tm.gyro_x_samples,
        "gyro_y_samples": tm.gyro_y_samples,
        "gyro_z_samples": tm.gyro_z_samples,
        "gyro_magnitude_samples": tm.gyro_magnitude_samples,
    }

    out_file = str(OUT_DIR / f"{tag}_{frames}f.mp4")
    for p in [Path(out_file), Path(out_file + ".amd_profile.json")]:
        if p.exists():
            p.unlink()

    fps = 59.94005994 if "GX010115" in str(video_path) else 30000.0 / 1001.0
    print(f"\n{'='*25} RUNNING: {tag} ({frames} frames) {'='*25}", flush=True)
    t0 = time.perf_counter()
    total = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(video_path)],
        output_file=out_file,
        duration_s=frames / fps,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        font_path="arial.ttf",
        layout=layout,
        field_samples=field_samples,
        max_distance_m=(tm.track_samples[-1][1] if tm.track_samples else 0),
        target_fps=fps,
        workers=4,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples,
        gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source(
            layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
        ),
        encoder="amd",
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        rotation_degrees=rotation_degrees,
    )
    wall = time.perf_counter() - t0
    print(f"COMPLETED {tag}: total_frames={total}, wall={wall:.3f}s", flush=True)

    prof = json.load(open(out_file + ".amd_profile.json")) if Path(out_file + ".amd_profile.json").exists() else {}
    return prof

if __name__ == "__main__":
    V_1131 = Path("Video/GX010115.MP4")
    V_300 = Path("Video/GX030120.MP4")
    FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
    PRESET_V10 = "presets/cycling_dashboard_v10.json"
    LAYOUT_DEF = "def_layout.json"

    results = {}

    # 1. Reference Workload: 1131f GX010115, v10 preset
    print("\n" + "#"*80)
    print("STEP 1: 1131 FRAMES REFERENCE WORKLOAD (GX010115 / v10 / 4K)")
    print("#"*80)
    results["1131f_ref_cpu_lean"] = execute_run("ref_1131f_cpu_lean", V_1131, FIT, PRESET_V10, 1131, {"AMD_LEAN_GPU": "0"})
    results["1131f_cand_gpu_lean"] = execute_run("cand_1131f_gpu_lean", V_1131, FIT, PRESET_V10, 1131, {"AMD_LEAN_GPU": "1"})

    # 2. Ablation Matrix on def_layout (300f GX030120)
    print("\n" + "#"*80)
    print("STEP 2: ABLATION MATRIX (300 FRAMES, def_layout)")
    print("#"*80)
    results["abl_full"] = execute_run("abl_full", V_300, FIT, LAYOUT_DEF, 300, {
        "AMD_LEAN_GPU": "1", "AMD_AFTER_MAP_GAUGE_GPU": "1", "AMD_GPU_MAP_ROTATE": "1", "AMD_CHART_PATH": "GPU_SPLIT"
    })
    results["abl_lean_off"] = execute_run("abl_lean_off", V_300, FIT, LAYOUT_DEF, 300, {
        "AMD_LEAN_GPU": "0", "AMD_AFTER_MAP_GAUGE_GPU": "1", "AMD_GPU_MAP_ROTATE": "1", "AMD_CHART_PATH": "GPU_SPLIT"
    })
    results["abl_gauge_off"] = execute_run("abl_gauge_off", V_300, FIT, LAYOUT_DEF, 300, {
        "AMD_LEAN_GPU": "1", "AMD_AFTER_MAP_GAUGE_GPU": "0", "AMD_GPU_MAP_ROTATE": "1", "AMD_CHART_PATH": "GPU_SPLIT"
    })
    results["abl_charts_off"] = execute_run("abl_charts_off", V_300, FIT, LAYOUT_DEF, 300, {
        "AMD_LEAN_GPU": "1", "AMD_AFTER_MAP_GAUGE_GPU": "1", "AMD_GPU_MAP_ROTATE": "1", "AMD_CHART_PATH": "CPU_REFERENCE"
    })
    results["abl_map_rotate_off"] = execute_run("abl_map_rotate_off", V_300, FIT, LAYOUT_DEF, 300, {
        "AMD_LEAN_GPU": "1", "AMD_AFTER_MAP_GAUGE_GPU": "1", "AMD_GPU_MAP_ROTATE": "0", "AMD_CHART_PATH": "GPU_SPLIT"
    })

    # 3. Soak Test: 2001 frames GX010115
    print("\n" + "#"*80)
    print("STEP 3: SOAK TEST (2001 FRAMES GX010115 / v10)")
    print("#"*80)
    results["soak_2001f"] = execute_run("soak_2001f", V_1131, FIT, PRESET_V10, 2001, {"AMD_LEAN_GPU": "1"})

    # Dump all results
    with open(OUT_DIR / "etap3a_all_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\nALL RUNS COMPLETED SUCCESSFULLY. Results saved to scratch/etap3a_bench/etap3a_all_results.json")
