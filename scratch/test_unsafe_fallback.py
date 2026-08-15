"""Verify the ETAP 5G GPU_MAP_UNSAFE_LAYOUT -> CPU_REFERENCE fallback."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.gui.layout_manager import resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    extract_speed_samples,
    extract_altitude_samples,
    extract_track_samples,
    extract_iso_samples,
    extract_exposure_samples,
    extract_temperature_samples,
    interpolate_value,
    smooth_speed_samples,
)

os.environ["AMD_MAP_PATH"] = "GPU"          # request GPU
os.environ["AMD_MAP_FILTER"] = "LANCZOS"
os.environ["AMD_MAP_AB_READBACK"] = "0"
os.environ["AMD_OVERLAY_PROFILE"] = "0"
os.environ["AMD_NATIVE_PROFILING"] = "0"
os.environ["AMD_NATIVE_DIAGNOSTICS"] = "0"
# clean source requires the CPU-decode reference mode (no GoPro VUI metadata)
os.environ["AMD_NATIVE_DECODE_MODE"] = "GPU_HUD_CPU_DECODE_REFERENCE"

video = ROOT / "Raporty" / "AMD_ETAP5G" / "VAL" / "clean_m10.mp4"
telemetry = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
)
telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
telemetry.start_dt_utc = __import__("datetime").datetime(2026, 8, 5, 4, 28, 11)

with (ROOT / "scratch" / "layout_unsafe.json").open(encoding="utf-8") as handle:
    layout = json.load(handle)

speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
track = telemetry.track_samples
result = stream_overlay_to_ffmpeg(
    ffmpeg_exe=r"C:\tools\ffmpeg.exe",
    input_files=[str(video)],
    output_file=str(ROOT / "Raporty" / "AMD_ETAP5G" / "VAL" / "unsafe_fallback_clean.mp4"),
    duration_s=30 * (1001.0 / 30000.0),
    start_dt_utc=telemetry.start_dt_utc,
    tz_offset_hours=2,
    speed_samples=speed,
    track_samples=track,
    alt_samples=altitude,
    font_path=resolve_font_path("Arial"),
    layout=layout,
    field_samples={
        "speed_samples": speed,
        "track_samples": track,
        "alt_samples": altitude,
    },
    max_distance_m=track[-1][1] if track else 0,
    target_fps=30000 / 1001,
    update_rate_step=1,
    workers=1,
    iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples,
    temperature_samples=telemetry.temperature_samples,
    gpx_speed_samples=telemetry.gpx_speed_samples,
    gpx_track_samples=telemetry.gpx_track_samples,
    gpx_alt_samples=telemetry.gpx_alt_samples,
    gpx_power_samples=telemetry.gpx_power_samples,
    gpx_atemp_samples=telemetry.gpx_atemp_samples,
    gpx_hr_samples=telemetry.gpx_hr_samples,
    gpx_cad_samples=telemetry.gpx_cad_samples,
    fit_data=telemetry.fit_data,
    gps_track=telemetry.get_gps_track_for_source(
        layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
    ),
    encoder="amd",
    gpu=0,
    video_bitrate="40M",
    render_w=3840,
    render_h=2160,
    resolution_name="source",
    rotation_degrees=180,
    container_rotation=180,
    overlay_w=1920,
    overlay_h=1080,
)
print(f"RESULT: {result} (expected ~30 frames)")
