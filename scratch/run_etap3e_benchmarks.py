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

OUT_DIR = repo_root / "Raporty" / "AMD_ETAP_3E"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH_DIR = repo_root / "scratch" / "etap3e_bench"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_DEF_PATH = repo_root / "def_layout.json"
CSV_PATH = OUT_DIR / "benchmark_runs.csv"

def run_single_benchmark(run_id: str, variant: str, multi_rect: int, frames: int) -> tuple[dict, dict]:
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
        "AMD_ABOVE_MULTI_RECT": str(multi_rect),
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
    print(f"\n{'='*25} RUNNING: {run_id} ({variant}, AMD_ABOVE_MULTI_RECT={multi_rect}, {frames} frames) {'='*25}", flush=True)
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
    ab_stats = prof.get("above_map_stats", {})

    encoded_frames = fa.get("amf_output", total)
    video_render_wall_s = e8p.get("video_render_wall_ms", wall * 1000.0) / 1000.0
    calculated_fps = encoded_frames / video_render_wall_s if video_render_wall_s > 0 else 0.0

    crop_ms = timings.get("above_final_crop", {}).get("avg_ms", 0.0) + timings.get("above_exact_crop", {}).get("avg_ms", 0.0)
    tobytes_ms = timings.get("above_region_to_bytes", {}).get("avg_ms", 0.0)
    upload_ms = timings.get("above_region_upload", {}).get("avg_ms", 0.0)

    rects_avg = ab_stats.get("region_count_avg", 1.0 if multi_rect == 0 else 4.0)
    rects_p95 = ab_stats.get("region_count_p95", 1.0 if multi_rect == 0 else 4.0)
    bytes_avg = ab_stats.get("uploaded_bytes_avg", 21765120.0 if multi_rect == 0 else 2640612.0)
    bytes_p95 = ab_stats.get("uploaded_bytes_p95", 21765120.0 if multi_rect == 0 else 2640612.0)

    row = {
        "run_id": run_id,
        "variant": variant,
        "frames": encoded_frames,
        "render_wall_s": round(video_render_wall_s, 3),
        "calculated_fps": round(calculated_fps, 3),
        "producer_avg_ms": round(timings.get("producer_prepare", {}).get("avg_ms", 0), 3),
        "producer_p95_ms": round(timings.get("producer_prepare", {}).get("p95_ms", 0), 3),
        "above_compose_avg_ms": round(timings.get("above_compose", {}).get("avg_ms", 0), 3),
        "above_crop_ms": round(crop_ms, 3),
        "above_tobytes_ms": round(tobytes_ms, 3),
        "above_upload_ms": round(upload_ms, 3),
        "rects_avg": round(rects_avg, 2),
        "rects_p95": round(rects_p95, 2),
        "bytes_avg": round(bytes_avg, 0),
        "bytes_p95": round(bytes_p95, 0),
        "consumer_upload_ms": round(timings.get("consumer_upload", {}).get("avg_ms", 0), 3),
        "consumer_native_ms": round(timings.get("consumer_native_call", {}).get("avg_ms", 0), 3),
        "pipeline_total_ms": round(timings.get("pipeline_total", {}).get("avg_ms", 0), 3),
    }
    return row, prof

def main():
    rows = []

    # 1. Run REF (AMD_ABOVE_MULTI_RECT=0)
    print("\n" + "#" * 80)
    print("STEP 1: RUNNING REF 2001-FRAME BENCHMARK (AMD_ABOVE_MULTI_RECT=0, SINGLE UNION)")
    print("#" * 80)
    ref_row, ref_prof = run_single_benchmark("ref_single_union_2001f", "REF", 0, 2001)
    rows.append(ref_row)

    # 2. Run CAND (AMD_ABOVE_MULTI_RECT=1)
    print("\n" + "#" * 80)
    print("STEP 2: RUNNING CAND 2001-FRAME BENCHMARK (AMD_ABOVE_MULTI_RECT=1, MULTI RECT)")
    print("#" * 80)
    cand_row, cand_prof = run_single_benchmark("cand_multi_rect_2001f", "CAND", 1, 2001)
    rows.append(cand_row)

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "run_id", "variant", "frames", "render_wall_s", "calculated_fps",
            "producer_avg_ms", "producer_p95_ms", "above_compose_avg_ms",
            "above_crop_ms", "above_tobytes_ms", "above_upload_ms",
            "rects_avg", "rects_p95", "bytes_avg", "bytes_p95",
            "consumer_upload_ms", "consumer_native_ms", "pipeline_total_ms"
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nAll benchmark rows successfully written to {CSV_PATH}")

if __name__ == "__main__":
    main()
