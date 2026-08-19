"""Generate all 8 stage comparison images and verify chart label clipping fix."""
import sys
import subprocess
from pathlib import Path
from PIL import Image
import numpy as np
from datetime import timedelta

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
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.chart_builder import build_chart_data
from src.indicators.dispatcher import render_value_indicator
from src.indicators.chart import ChartSplit
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

out_dir = root / "Raporty" / "etap8m6_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

video_path = root / "Video" / "GX020079.mp4"
json_path = root / "Video" / "GX020079.json"
fit_path = root / "Video" / "Morning_Ride.fit"
layout_path = root / "def_layout.json"
font_path = "assets/Roboto-Bold.ttf"

# Initialize telemetry
telemetry = TelemetryDataManager(
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
telemetry.load_gpmf_records(records)
telemetry.load_fit(str(fit_path))

layout = normalize_layout(layout_path, 1920, 1080)
target_dt = telemetry.start_dt_utc + timedelta(seconds=18.87)

# Prepare ranges for activity scope
source_ranges = {"fit": (telemetry.start_dt_utc, telemetry.start_dt_utc + timedelta(seconds=1704))}

chart_data = build_chart_data(
    layout, telemetry.get_samples_for_source, telemetry.resolve_samples,
    start_dt_utc=telemetry.start_dt_utc, end_dt_utc=telemetry.start_dt_utc + timedelta(seconds=37.74),
    source_activity_ranges=source_ranges,
)

frame_data = prepare_overlay_frame_data(
    layout=layout,
    target_dt=target_dt,
    tz_offset_hours=2,
    start_dt_utc=telemetry.start_dt_utc,
    speed_samples=telemetry.speed_samples or [],
    track_samples=telemetry.track_samples or [],
    alt_samples=telemetry.alt_samples or [],
    iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples,
    temperature_samples=telemetry.temperature_samples,
    fit_data=telemetry.fit_data,
    chart_data=chart_data,
    resolve_cache_value=lambda field, src, dt, key=None: telemetry.resolve_value(field, dt, source=src, indicator_key=key),
)

# STAGE 1 & 2: Preview crops
p_bboxes = {}
p_canvas = compose_overlay(
    canvas_w=1920, canvas_h=1080, layout=layout, font_path=font_path,
    _bboxes=p_bboxes, gpu_capture_keys=None, reuse_canvas=False,
    **frame_data,
)

cad_box = p_bboxes["fit_cadence_text"]
hr_box = p_bboxes["fit_heart_rate_text"]

s1_cad = p_canvas.crop((cad_box[0], cad_box[1], cad_box[0] + cad_box[2], cad_box[1] + cad_box[3]))
s2_hr = p_canvas.crop((hr_box[0], hr_box[1], hr_box[0] + hr_box[2], hr_box[1] + hr_box[3]))
s1_cad.save(out_dir / "01_preview_chart_cad.png")
s2_hr.save(out_dir / "02_preview_chart_hr.png")
print("Saved 01_preview_chart_cad.png and 02_preview_chart_hr.png")

# STAGE 3 & 4: CPU chart raw
s3_cad, _, _, _ = render_value_indicator(
    canvas_w=1920, canvas_h=1080, layout=layout, font_path=font_path,
    key="fit_cadence_text", value=frame_data["extra_indicators"]["fit_cadence_text"][0],
    unit="rpm", label="Cadence", cfg_override=layout["indicators"]["fit_cadence_text"],
    history_data=chart_data.get("fit_cadence_text"), target_dt=target_dt,
)
s4_hr, _, _, _ = render_value_indicator(
    canvas_w=1920, canvas_h=1080, layout=layout, font_path=font_path,
    key="fit_heart_rate_text", value=frame_data["extra_indicators"]["fit_heart_rate_text"][0],
    unit="BPM", label="Heart Rate", cfg_override=layout["indicators"]["fit_heart_rate_text"],
    history_data=chart_data.get("fit_heart_rate_text"), target_dt=target_dt,
)
s3_cad.save(out_dir / "03_cpu_chart_cad.png")
s4_hr.save(out_dir / "04_cpu_chart_hr.png")
print("Saved 03_cpu_chart_cad.png and 04_cpu_chart_hr.png")

# STAGE 5 & 6: GPU static chart
gpu_cap = {}
gpu_bboxes = {}
compose_overlay(
    canvas_w=1920, canvas_h=1080, layout=layout, font_path=font_path,
    _bboxes=gpu_bboxes, gpu_capture_keys={"fit_cadence_text", "fit_heart_rate_text"},
    gpu_capture=gpu_cap, split_chart_keys={"fit_cadence_text", "fit_heart_rate_text"},
    reuse_canvas=False, **frame_data,
)
s5_cad = gpu_cap["fit_cadence_text"]["static"]
s6_hr = gpu_cap["fit_heart_rate_text"]["static"]
s5_cad.save(out_dir / "05_gpu_static_chart_cad.png")
s6_hr.save(out_dir / "06_gpu_static_chart_hr.png")
print("Saved 05_gpu_static_chart_cad.png and 06_gpu_static_chart_hr.png")

# STAGE 7 & 8: Final AMD video crops
mp4_path = out_dir / "charts_test_out.mp4"
if mp4_path.exists():
    mp4_path.unlink()

export_amd_native_d3d11(
    ffmpeg_exe="ffmpeg",
    input_files=[str(video_path)],
    output_file=str(mp4_path),
    duration_s=2.0,
    video_width=1920,
    video_height=1080,
    start_dt_utc=telemetry.start_dt_utc,
    tz_offset_hours=2.0,
    speed_samples=telemetry.speed_samples or [],
    track_samples=telemetry.track_samples or [],
    alt_samples=telemetry.alt_samples or [],
    font_path=font_path,
    layout=layout,
    field_samples=telemetry.fit_data or {},
    iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples,
    temperature_samples=telemetry.temperature_samples,
    fit_data=telemetry.fit_data,
    gps_track=telemetry.get_gps_track_for_source("fit"),
)

frame_png = out_dir / "charts_final_frame.png"
cmd = [
    "ffmpeg", "-y", "-ss", "00:00:01", "-i", str(mp4_path),
    "-frames:v", "1", "-q:v", "2", str(frame_png),
]
subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
final_frame = Image.open(frame_png)
s7_cad = final_frame.crop((cad_box[0], cad_box[1], min(1920, cad_box[0] + cad_box[2]), min(1080, cad_box[1] + cad_box[3])))
s8_hr = final_frame.crop((hr_box[0], hr_box[1], min(1920, hr_box[0] + hr_box[2]), min(1080, hr_box[1] + hr_box[3])))
s7_cad.save(out_dir / "07_final_chart_cad.png")
s8_hr.save(out_dir / "08_final_chart_hr.png")
print("Saved 07_final_chart_cad.png and 08_final_chart_hr.png")

# Also save Section 28 required crops: cad_preview.png, cad_final.png, hr_preview.png, hr_final.png
s1_cad.save(out_dir / "cad_preview.png")
s7_cad.save(out_dir / "cad_final.png")
s2_hr.save(out_dir / "hr_preview.png")
s8_hr.save(out_dir / "hr_final.png")
print("Saved cad_preview.png, cad_final.png, hr_preview.png, hr_final.png")
