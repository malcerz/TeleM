import csv
import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import (
    get_rotation_from_metadata,
    load_json_with_fallback,
    ensure_records_list,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

OUT_DIR = repo_root / "Raporty" / "AMD_ETAP_3C"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH_DIR = repo_root / "scratch" / "etap3c_bench"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_DEF_PATH = repo_root / "def_layout.json"
CSV_PATH = OUT_DIR / "benchmark_runs.csv"

def run_single_benchmark(run_id: str, variant: str, frames: int) -> dict:
    env_clean = {
        "AMD_NATIVE_DIAGNOSTICS": "0",
        "AMD_NATIVE_PROFILING": "0",
        "AMD_GPU_TIMESTAMP_PROFILE": "0",
        "AMD_NATIVE_FRAME_ACCOUNTING": "0",
        "AMD_AMF_MODE": "ENCODE",
        "AMD_GPU_MAP_ROTATE": "1",
        "AMD_AFTER_MAP_CHART_GPU": "1",
        "AMD_AFTER_MAP_GAUGE_GPU": "1",
        "AMD_LEAN_GPU": "1",
    }
    for k, v in env_clean.items():
        os.environ[k] = str(v)

    tm = TelemetryDataManager()
    processed = read_processed_cache(VIDEO)
    if processed is not None:
        apply_processed_cache(tm, processed)
    else:
        tm.load_gpmf_from_exiftool(VIDEO)
    tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

    records = ensure_records_list(
        load_json_with_fallback(VIDEO.with_suffix(".json"))
    )
    rotation_degrees = get_rotation_from_metadata(records)

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

    layout = json.load(open(LAYOUT_DEF_PATH, encoding="utf-8"))
    out_file = str(SCRATCH_DIR / f"{run_id}_{frames}f.mp4")
    for p in [Path(out_file), Path(out_file + ".amd_profile.json")]:
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    fps = 30000.0 / 1001.0
    print(f"\n{'='*25} RUNNING: {run_id} ({variant}, {frames} frames) {'='*25}", flush=True)
    t0 = time.perf_counter()
    total = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(VIDEO)],
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

    prof_p = Path(out_file + ".amd_profile.json")
    prof = json.load(open(prof_p)) if prof_p.exists() else {}
    timings = prof.get("timings", {})
    fa = prof.get("frame_accounting", {})
    e8p = prof.get("etap8pa_summary", {})

    encoded_frames = fa.get("amf_output", total)
    video_render_wall_s = e8p.get("video_render_wall_ms", wall * 1000.0) / 1000.0
    calculated_fps = encoded_frames / video_render_wall_s if video_render_wall_s > 0 else 0.0

    row = {
        "run_id": run_id,
        "variant": variant,
        "frames": encoded_frames,
        "video_render_wall_s": round(video_render_wall_s, 3),
        "calculated_fps": round(calculated_fps, 3),
        "producer_avg_ms": round(timings.get("producer_prepare", {}).get("avg_ms", 0), 3),
        "above_avg_ms": round(timings.get("above_compose", {}).get("avg_ms", 0), 3),
        "above_total_ms": round(timings.get("above_total", {}).get("avg_ms", 0), 3),
        "consumer_avg_ms": round(timings.get("consumer_native_call", {}).get("avg_ms", 0), 3),
    }
    return row, prof

def main():
    csv_exists = CSV_PATH.exists()
    rows = []
    
    # 1. Short A/B (600 frames)
    print("\n" + "#" * 80)
    print("STEP 1: 600-FRAME SHORT PIPELINE A/B (CAND TEXT + BAR)")
    print("#" * 80)
    r_short, p_short = run_single_benchmark("cand_text_600f", "CAND_TEXT", 600)
    rows.append(r_short)

    # 2. Long A/B (2001 frames)
    print("\n" + "#" * 80)
    print("STEP 2: 2001-FRAME LONG PIPELINE A/B (CAND TEXT + BAR)")
    print("#" * 80)
    r_long, p_long = run_single_benchmark("cand_text_2001f", "CAND_TEXT", 2001)
    rows.append(r_long)

    # Also record REF long baseline for comparison
    raw_3b = json.load(open(repo_root / "Raporty" / "AMD_ETAP_3B" / "etap3b_audit_raw.json"))
    ref_prof = raw_3b["long_baseline_2001f"]
    ref_timings = ref_prof.get("timings", {})
    ref_wall_s = (ref_prof.get("total_wall_clock_s", 83.187) - ref_timings.get("Audio mux", {}).get("avg_ms", 3181.0) / 1000.0)
    ref_row = {
        "run_id": "ref_baseline_2001f",
        "variant": "REF_BASELINE",
        "frames": 2001,
        "video_render_wall_s": round(ref_wall_s, 3),
        "calculated_fps": round(2001.0 / ref_wall_s, 3),
        "producer_avg_ms": round(ref_timings.get("producer_prepare", {}).get("avg_ms", 25.070), 3),
        "above_avg_ms": round(ref_timings.get("above_compose", {}).get("avg_ms", 18.160), 3),
        "above_total_ms": round(ref_timings.get("above_total", {}).get("avg_ms", 19.336), 3),
        "consumer_avg_ms": round(ref_timings.get("consumer_native_call", {}).get("avg_ms", 2.226), 3),
    }

    all_rows = [ref_row] + rows
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "run_id", "variant", "frames", "video_render_wall_s", "calculated_fps",
            "producer_avg_ms", "above_avg_ms", "above_total_ms", "consumer_avg_ms"
        ])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nAll benchmark rows successfully written to {CSV_PATH}")

if __name__ == "__main__":
    main()
