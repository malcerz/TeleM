"""
Smoke performance & visual validation of Preview ON vs Preview OFF (300 frames).
"""
import sys
import time
import json
from pathlib import Path
sys.path.insert(0, str(Path("c:/_DEV/TeleM")))

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.gui.qt.tabs.render_tab import RenderTab
from PySide6.QtWidgets import QApplication
from datetime import datetime, timezone
from PIL import Image

app = QApplication.instance() or QApplication([])

root = Path("c:/_DEV/TeleM")
def_layout_path = root / "def_layout.json"
with open(def_layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

font_path = resolve_font_path("Arial")
video_path = root / "Video" / "GX030120.MP4"
json_path = root / "Video" / "GX030120.json"
fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"

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
raw_data = load_json_with_fallback(json_path)
records = ensure_records_list(raw_data)
telemetry.load_gpmf_records(records)
telemetry.load_gps_track(records)
telemetry.load_fit(str(fit_path))

field_samples = {
    "speed_samples": telemetry.speed_samples,
    "track_samples": telemetry.track_samples,
    "alt_samples": telemetry.alt_samples,
    "iso_samples": telemetry.iso_samples,
    "exposure_samples": telemetry.exposure_samples,
    "temperature_samples": telemetry.temperature_samples,
    "accel_x_samples": telemetry.accel_x_samples,
    "accel_y_samples": telemetry.accel_y_samples,
    "accel_z_samples": telemetry.accel_z_samples,
    "accel_magnitude_samples": telemetry.accel_magnitude_samples,
    "gyro_x_samples": telemetry.gyro_x_samples,
    "gyro_y_samples": telemetry.gyro_y_samples,
    "gyro_z_samples": telemetry.gyro_z_samples,
    "gyro_magnitude_samples": telemetry.gyro_magnitude_samples,
}

render_tab = RenderTab()
class RealController:
    video_paths = [str(video_path)]
    video_path = str(video_path)
    video_duration_s = 5.0
    font_path = font_path
    ffmpeg_exe = "ffmpeg"
    ffprobe_exe = "ffprobe"
    layout = layout
    telemetry = telemetry
    last_src_pil = Image.new("RGBA", (960, 540), (20, 30, 40, 255))
render_tab._controller = RealController()
render_tab._controller = RealController()
render_tab._rendering = True
render_tab._render_total = 150

preview_frames_generated = []

def preview_on_progress(completed, total, elapsed, fps, hud_state):
    render_tab._on_render_progress(completed, total, elapsed, fps, hud_state)
    app.processEvents()
    if render_tab.hud_preview_label.pixmap() is not None:
        preview_frames_generated.append((completed, render_tab._hud_ts))

print("===============================================================================")
print("RUN 1: PREVIEW ON (150 frames @ 4K)")
print("===============================================================================")
t0 = time.perf_counter()
success1 = export_amd_native_d3d11(
    ffmpeg_exe="ffmpeg",
    input_files=[str(video_path)],
    output_file=str(root / "scratch" / "smoke_preview_on.mp4"),
    duration_s=2.5,  # 150 frames @ 59.94 fps
    video_width=3840,
    video_height=2160,
    start_dt_utc=telemetry.start_dt_utc,
    tz_offset_hours=2,
    speed_samples=telemetry.speed_samples,
    track_samples=telemetry.track_samples,
    alt_samples=telemetry.alt_samples,
    font_path=font_path,
    layout=layout,
    field_samples=field_samples,
    target_fps=59.94,
    video_bitrate="40M",
    fit_data=telemetry.fit_data,
    gps_track=telemetry.get_gps_track_for_source("fit"),
    on_render_progress=preview_on_progress,
)
t_preview_on = time.perf_counter() - t0
fps_preview_on = 150.0 / t_preview_on

print(f"Preview ON time: {t_preview_on:.2f}s ({fps_preview_on:.2f} FPS)")
print(f"Preview updates received: {len(preview_frames_generated)}")
last_pix = render_tab.hud_preview_label.pixmap()
if last_pix:
    last_pix.save(str(root / "scratch" / "last_preview_frame.png"))
    print("Saved last preview frame to scratch/last_preview_frame.png")

print("\n===============================================================================")
print("RUN 2: PREVIEW OFF (150 frames @ 4K)")
print("===============================================================================")
t0 = time.perf_counter()
success2 = export_amd_native_d3d11(
    ffmpeg_exe="ffmpeg",
    input_files=[str(video_path)],
    output_file=str(root / "scratch" / "smoke_preview_off.mp4"),
    duration_s=2.5,
    video_width=3840,
    video_height=2160,
    start_dt_utc=telemetry.start_dt_utc,
    tz_offset_hours=2,
    speed_samples=telemetry.speed_samples,
    track_samples=telemetry.track_samples,
    alt_samples=telemetry.alt_samples,
    font_path=font_path,
    layout=layout,
    field_samples=field_samples,
    target_fps=59.94,
    video_bitrate="40M",
    fit_data=telemetry.fit_data,
    gps_track=telemetry.get_gps_track_for_source("fit"),
    on_render_progress=None,
)
t_preview_off = time.perf_counter() - t0
fps_preview_off = 150.0 / t_preview_off

print(f"Preview OFF time: {t_preview_off:.2f}s ({fps_preview_off:.2f} FPS)")
diff_pct = ((t_preview_on - t_preview_off) / t_preview_off) * 100.0
print(f"Relative difference: {diff_pct:+.2f}%")

print("\n===============================================================================")
print("SUMMARY RESULTS")
print("===============================================================================")
print(f"PREVIEW ON  = {fps_preview_on:.2f} FPS")
print(f"PREVIEW OFF = {fps_preview_off:.2f} FPS")
print(f"OVERHEAD    = {abs(diff_pct):.2f}% (Target: <= 2.0%)")
