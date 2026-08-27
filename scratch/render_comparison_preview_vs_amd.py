import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path
from PIL import Image

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import (
    get_rotation_from_metadata,
    load_json_with_fallback,
    ensure_records_list,
)
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = repo_root / "def_layout.json"

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

fps = 30000.0 / 1001.0
frame_idx = 150
target_dt = tm.start_dt_utc + timedelta(seconds=frame_idx / fps) if tm.start_dt_utc else None

# 1. RENDER REFERENCE PREVIEW FRAME
frame_kwargs = prepare_overlay_frame_data(
    layout=layout,
    target_dt=target_dt,
    tz_offset_hours=2,
    start_dt_utc=tm.start_dt_utc,
    speed_samples=tm.speed_samples,
    track_samples=tm.track_samples,
    alt_samples=tm.alt_samples,
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source(
        layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
    ),
    fit_field_plan=fit_field_plan,
)

print("Rendering CPU Reference Frame 150...")
ref_img = compose_overlay(
    canvas_w=3840,
    canvas_h=2160,
    layout=layout,
    font_path="arial.ttf",
    **frame_kwargs
)
ref_img.save(repo_root / "scratch" / "reference_frame_150.png")
print("Saved scratch/reference_frame_150.png")

# 2. EXPORT AMD NATIVE D3D11 VIDEO (300 frames)
out_mp4 = repo_root / "scratch" / "test_amd_etap3m_smoke.mp4"
if out_mp4.exists():
    try:
        out_mp4.unlink()
    except Exception:
        pass

records = ensure_records_list(load_json_with_fallback(VIDEO.with_suffix(".json")))
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

print("Running AMD Native Export for 300 frames...")
stream_overlay_to_ffmpeg(
    ffmpeg_exe=r"C:\tools\ffmpeg.exe",
    input_files=[str(VIDEO)],
    output_file=str(out_mp4),
    duration_s=300 / fps,
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

# Extract frame 150 from out_mp4
import subprocess
frame_out = str(repo_root / "scratch" / "amd_frame_150.png")
subprocess.run([
    r"C:\tools\ffmpeg.exe", "-y", "-ss", f"{150 / fps:.3f}",
    "-i", str(out_mp4), "-vframes", "1", frame_out
], check=True)

print("Saved scratch/amd_frame_150.png")
