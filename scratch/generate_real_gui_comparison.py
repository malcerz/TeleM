"""Generate all requested real GUI preview and final comparison screenshots for ETAP 8M.5."""
import sys
import subprocess
from pathlib import Path
from PIL import Image
import numpy as np

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
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

out_dir = root / "Raporty" / "etap8m5_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

video_path = root / "Video" / "GX020079.mp4"
json_path = root / "Video" / "GX020079.json"
fit_path = root / "Video" / "Morning_Ride.fit"
layout_path = root / "def_layout.json"
font_path = "assets/Roboto-Bold.ttf"

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

base_layout = normalize_layout(layout_path, 1920, 1080)
from datetime import timedelta
target_dt = telemetry.start_dt_utc + timedelta(seconds=18.87)

chart_data = build_chart_data(
    base_layout, telemetry.get_samples_for_source, telemetry.resolve_samples,
    start_dt_utc=telemetry.start_dt_utc, end_dt_utc=telemetry.start_dt_utc + timedelta(seconds=37.74),
)

variations = [
    ("default", {}),
    ("tick_a", {"ticks": 4}),
    ("tick_b", {"ticks": 20}),
    ("width_a", {"thickness": 1}),
    ("width_b", {"thickness": 5}),
]

for var_name, overrides in variations:
    cur_layout = normalize_layout(layout_path, 1920, 1080)
    for k, v in overrides.items():
        cur_layout["indicators"]["fit_enhanced_speed_text"][k] = v

    frame_data = prepare_overlay_frame_data(
        layout=cur_layout,
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

    # 1. Preview
    p_bboxes = {}
    p_canvas = compose_overlay(
        canvas_w=1920, canvas_h=1080,
        layout=cur_layout, font_path=font_path,
        _bboxes=p_bboxes,
        gpu_capture_keys=None,
        reuse_canvas=False,
        **frame_data,
    )
    gx, gy, gw, gh = p_bboxes["fit_enhanced_speed_text"]
    preview_crop = p_canvas.crop((gx, gy, gx + gw, gy + gh))
    preview_crop.save(out_dir / f"real_gui_preview_{var_name}.png")

    # 2. Final AMD export
    mp4_path = out_dir / f"test_{var_name}.mp4"
    if mp4_path.exists():
        mp4_path.unlink()
    export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(video_path)],
        output_file=str(mp4_path),
        duration_s=1.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=telemetry.start_dt_utc,
        tz_offset_hours=2.0,
        speed_samples=telemetry.speed_samples or [],
        track_samples=telemetry.track_samples or [],
        alt_samples=telemetry.alt_samples or [],
        font_path=font_path,
        layout=cur_layout,
        field_samples=telemetry.fit_data or {},
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
    )

    frame_png = out_dir / f"frame_{var_name}.png"
    cmd = [
        "ffmpeg", "-y", "-ss", "00:00:00.5", "-i", str(mp4_path),
        "-frames:v", "1", "-q:v", "2", str(frame_png),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    final_frame = Image.open(frame_png)
    final_crop = final_frame.crop((gx, gy, min(1920, gx + gw), min(1080, gy + gh)))
    final_crop.save(out_dir / f"real_gui_final_{var_name}.png")
    print(f"Generated real_gui_preview_{var_name}.png and real_gui_final_{var_name}.png")
