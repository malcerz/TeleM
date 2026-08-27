import json
import os
import sys
import time
from pathlib import Path

os.environ["AMD_NATIVE_DIAGNOSTICS"] = "1"
os.environ["AMD_AMF_MODE"] = "ENCODE"
os.environ["AMD_GPU_MAP_ROTATE"] = "1"
os.environ["AMD_CHART_PATH"] = "GPU_SPLIT"
os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import (
    get_rotation_from_metadata,
    load_json_with_fallback,
    ensure_records_list,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

VIDEO = Path("Video/GX030120.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
OUT_DIR = Path("scratch/etap2g_bench")
FRAMES = 300
FPS = 30000.0 / 1001.0


def run_workload(mode_name: str, lean_gpu: bool):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layout = json.load(open("def_layout.json", encoding="utf-8"))

    os.environ["AMD_LEAN_GPU"] = "1" if lean_gpu else "0"

    tm = TelemetryDataManager()
    processed = read_processed_cache(VIDEO)
    assert processed is not None, "processed cache missing"
    apply_processed_cache(tm, processed)

    records = ensure_records_list(
        load_json_with_fallback(VIDEO.with_suffix(".json"))
    )
    rotation_degrees = get_rotation_from_metadata(records)
    fit_ok = tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

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

    out_file = str(OUT_DIR / f"{mode_name}_300f.mp4")
    if Path(out_file).exists():
        Path(out_file).unlink()
    profile_path = Path(out_file + ".amd_profile.json")
    if profile_path.exists():
        profile_path.unlink()

    print(f"\n{'='*20} RUNNING WORKLOAD: {mode_name} (AMD_LEAN_GPU={1 if lean_gpu else 0}) {'='*20}", flush=True)
    t0 = time.perf_counter()
    total = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(VIDEO)],
        output_file=out_file,
        duration_s=FRAMES / FPS,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        font_path="arial.ttf",
        layout=layout,
        field_samples=field_samples,
        max_distance_m=(tm.track_samples[-1][1] if tm.track_samples else 0),
        target_fps=FPS,
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
    print(f"DONE {mode_name}: total={total} frames in {wall:.3f}s ({total/wall:.2f} fps)", flush=True)

    prof = json.load(open(profile_path, encoding="utf-8"))
    return prof


def main():
    prof_cpu = run_workload("lean_cpu", lean_gpu=False)
    prof_gpu = run_workload("lean_gpu", lean_gpu=True)

    print("\n" + "="*60)
    print("ETAP 2G BENCHMARK COMPARISON (300 frames, 4K def_layout.json)")
    print("="*60)
    print(f"{'Metric':<32} {'CPU Tight (2F-B)':<18} {'GPU Lean (2G)':<18} {'Delta'}")
    print("-" * 75)

    metrics = [
        ("RENDER FPS", "fps_native_render", True),
        ("USER EFFECTIVE FPS", "fps_user_effective", True),
        ("above_compose (ms)", "above_compose", False),
        ("above_total (ms)", "above_total", False),
        ("producer_prepare (ms)", "producer_prepare", False),
        ("consumer_native_call (ms)", "consumer_native_call", False),
        ("pipeline_total (ms)", "pipeline_total", False),
    ]

    for label, key, is_fps in metrics:
        if is_fps:
            v_cpu = prof_cpu.get("rates", {}).get(key, 0.0)
            v_gpu = prof_gpu.get("rates", {}).get(key, 0.0)
            diff = v_gpu - v_cpu
            pct = (diff / max(1e-6, v_cpu)) * 100.0
            print(f"{label:<32} {v_cpu:<18.3f} {v_gpu:<18.3f} {diff:+.3f} ({pct:+.1f}%)")
        else:
            v_cpu = prof_cpu.get("averages_ms", {}).get(key, 0.0)
            v_gpu = prof_gpu.get("averages_ms", {}).get(key, 0.0)
            diff = v_gpu - v_cpu
            pct = (diff / max(1e-6, v_cpu)) * 100.0
            print(f"{label:<32} {v_cpu:<18.3f} {v_gpu:<18.3f} {diff:+.3f} ms ({pct:+.1f}%)")

    # Save summary report data
    summary = {
        "cpu": prof_cpu,
        "gpu": prof_gpu,
    }
    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
