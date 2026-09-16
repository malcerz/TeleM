"""Short production final smoke for the GoPro battery startup contract."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telemetry_fit import parse_fit
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import apply_processed_cache, read_processed_cache

VIDEO = Path("D:/GoPro/2026-09-02/GX010246.MP4")
FIT = Path("D:/GoPro/2026-09-02/Poranna_jazda_na_rowerze.fit")
OUT = Path("D:/TeleM_live_acceptance/gopro_battery_startup/final_smoke_30f.mp4")
FPS = 30000.0 / 1001.0

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
assert processed is not None, "processed telemetry cache missing"
apply_processed_cache(tm, processed)
assert tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)
layout = json.loads(Path("D:/GoPro/2026-09-02/GX010246.layout.json").read_text(encoding="utf-8"))
for cfg in layout.get("indicators", {}).values():
    cfg["enabled"] = False
layout["indicators"]["fit_gopro_battery_text"]["enabled"] = True
layout["indicators"]["fit_gopro_battery_text"].update(decimals=2, source="fit")
field_samples = {
    "speed_samples": tm.speed_samples, "track_samples": tm.track_samples,
    "alt_samples": tm.alt_samples, "heading_samples": tm.heading_samples,
    "gpx_heading_samples": tm.gpx_heading_samples, "slope_samples": tm.slope_samples,
    "gpx_slope_samples": tm.gpx_slope_samples, "iso_samples": tm.iso_samples,
    "exposure_samples": tm.exposure_samples, "temperature_samples": tm.temperature_samples,
    "accel_x_samples": tm.accel_x_samples, "accel_y_samples": tm.accel_y_samples,
    "accel_z_samples": tm.accel_z_samples, "accel_magnitude_samples": tm.accel_magnitude_samples,
    "gyro_x_samples": tm.gyro_x_samples, "gyro_y_samples": tm.gyro_y_samples,
    "gyro_z_samples": tm.gyro_z_samples, "gyro_magnitude_samples": tm.gyro_magnitude_samples,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
count = stream_overlay_to_ffmpeg(
    ffmpeg_exe=r"C:\tools\ffmpeg.exe", input_files=[str(VIDEO)], output_file=str(OUT),
    duration_s=30 / FPS, start_dt_utc=tm.start_dt_utc, tz_offset_hours=2,
    speed_samples=tm.speed_samples, track_samples=tm.track_samples, alt_samples=tm.alt_samples,
    font_path=r"C:\Windows\Fonts\arial.ttf", layout=layout, field_samples=field_samples,
    max_distance_m=(tm.track_samples[-1][1] if tm.track_samples else 0), target_fps=FPS,
    workers=2, iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples, fit_data=tm.fit_data,
    gps_track=tm.fit_gps_track, encoder="amd", video_bitrate="40M", render_w=3840,
    render_h=2160, resolution_name="source", rotation_degrees=0, container_rotation=0,
    overlay_w=3840, overlay_h=2160,
)
print("FINAL_SMOKE", count, OUT, OUT.exists(), OUT.stat().st_size if OUT.exists() else 0)
