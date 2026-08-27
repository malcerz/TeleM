import json
import os
import sys
import time
from pathlib import Path

os.environ["AMD_NATIVE_DIAGNOSTICS"] = "0"
os.environ["AMD_NATIVE_PROFILING"] = "0"
os.environ["AMD_GPU_TIMESTAMP_PROFILE"] = "0"
os.environ["AMD_NATIVE_FRAME_ACCOUNTING"] = "0"
os.environ["AMD_AMF_MODE"] = "ENCODE"
os.environ["AMD_GPU_MAP_ROTATE"] = "1"
os.environ["AMD_CHART_PATH"] = "GPU_SPLIT"
os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
os.environ["AMD_LEAN_GPU"] = "1"

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

VIDEO = Path("Video/GX030120.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
layout_file = "def_layout.json"
frames = 300

layout = json.load(open(layout_file, encoding="utf-8"))

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
assert processed is not None, f"processed cache missing for {VIDEO}"
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

out_file = str(OUT_DIR / f"prod_no_diag_{frames}f.mp4")
for p in [Path(out_file), Path(out_file + ".amd_profile.json")]:
    if p.exists():
        p.unlink()

fps = 30000.0 / 1001.0
print(f"\n{'='*25} RUNNING PRODUCTION TEST (NO DIAG / NO PROFILING SYNC) {'='*25}", flush=True)
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
print(f"COMPLETED: total_frames={total}, wall={wall:.3f}s", flush=True)

if Path(out_file + ".amd_profile.json").exists():
    prof = json.load(open(out_file + ".amd_profile.json"))
    timings = prof.get("timings", {})
    print("\n" + "="*80)
    print(f"TRUE FPS:             {prof.get('true_fps', 0):.3f}")
    for k in ["producer_prepare", "above_compose", "above_total", "consumer_upload", "consumer_native_call", "pipeline_total", "VideoProcessor GPU completion", "GPU wait/synchronization", "VideoProcessor CPU submit"]:
        if k in timings:
            t = timings[k]
            print(f"  {k:<32}: avg={t['avg_ms']:8.3f} ms, med={t['median_ms']:8.3f} ms, p95={t['p95_ms']:8.3f} ms")
    print("="*80)
