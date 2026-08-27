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

OUT_DIR = repo_root / "Raporty" / "AMD_ETAP_3J"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH_DIR = repo_root / "scratch" / "etap3j_bench"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_DEF_PATH = repo_root / "def_layout.json"
BENCH_CSV = OUT_DIR / "benchmark_runs.csv"

def run_benchmark_run(run_id: str, variant: str, sparse_compose: int, frames: int) -> dict:
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
        "AMD_ABOVE_MULTI_RECT": "1",
        "AMD_ABOVE_FINE_DIRTY": "0",
        "AMD_ABOVE_SPARSE_COMPOSE": str(sparse_compose),
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
    print(f"\n{'='*25} RUNNING: {run_id} ({variant}, SPARSE_COMPOSE={sparse_compose}, {frames}f) {'='*25}", flush=True)
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
    canonical_fps = encoded_frames / video_render_wall_s if video_render_wall_s > 0 else 0.0

    row = {
        "run": run_id,
        "sparse_compose": sparse_compose,
        "frames": encoded_frames,
        "render_wall": round(video_render_wall_s, 3),
        "canonical_fps": round(canonical_fps, 3),
        "producer": round(timings.get("producer_prepare", {}).get("avg_ms", 0), 3),
        "above_compose": round(timings.get("above_compose", {}).get("avg_ms", 0), 3),
        "above_total": round(timings.get("above_total", {}).get("avg_ms", 0), 3),
        "consumer_native": round(timings.get("consumer_native_call", {}).get("avg_ms", 0), 3),
        "pipeline_total": round(timings.get("pipeline_total", {}).get("avg_ms", 0), 3),
    }
    return row

def main():
    rows = []
    
    # Alternating Long A/B (2001 frames each): REF1, CAND1, REF2, CAND2, REF3, CAND3
    runs = [
        ("ref_1_long_2001f", "REF_PROD_1", 0, 2001),
        ("cand_1_long_2001f", "CAND_SPARSE_1", 1, 2001),
        ("ref_2_long_2001f", "REF_PROD_2", 0, 2001),
        ("cand_2_long_2001f", "CAND_SPARSE_2", 1, 2001),
        ("ref_3_long_2001f", "REF_PROD_3", 0, 2001),
        ("cand_3_long_2001f", "CAND_SPARSE_3", 1, 2001),
        # 3000-Frame Soak Test
        ("cand_soak_3000f", "CAND_SOAK_3000F", 1, 3000),
    ]

    for run_id, variant, sparse_compose, frames in runs:
        row = run_benchmark_run(run_id, variant, sparse_compose, frames)
        rows.append(row)

    with open(BENCH_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "run", "sparse_compose", "frames", "render_wall", "canonical_fps",
            "producer", "above_compose", "above_total", "consumer_native", "pipeline_total"
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nBenchmark runs written to {BENCH_CSV}")

if __name__ == "__main__":
    main()
