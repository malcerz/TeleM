import os
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.gui.telemetry_manager import TelemetryDataManager

# Clear any lingering environment variables
os.environ.pop("AMD_GPU_MAP_ROTATE", None)
os.environ.pop("AMD_AFTER_MAP_CHART_GPU", None)
os.environ.pop("AMD_MAP_PATH", None)
os.environ.pop("AMD_MAP_FILTER", None)
os.environ.pop("AMD_NATIVE_HUD_MODE", None)

PRESET = Path("presets/cycling_dashboard_v10.json")
VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

with open(PRESET, "r", encoding="utf-8") as f:
    layout = json.load(f)

telemetry = TelemetryDataManager()
telemetry.load_gpmf_from_exiftool(VIDEO)
telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
gps_track = telemetry.get_gps_track_for_source("fit")
fit_data = telemetry.fit_data

OUT_DIR = Path("scratch/etap1d_test")
OUT_DIR.mkdir(parents=True, exist_ok=True)
out_mp4 = OUT_DIR / "gui_smoke_render_120f.mp4"

print("=========================================================================")
print("NORMAL GUI AMD SMOKE RENDER (120 frames 4K, NO ENV SET)")
print("=========================================================================")

t0 = time.perf_counter()
ok = export_amd_native_d3d11(
    ffmpeg_exe="ffmpeg",
    input_files=[str(VIDEO)],
    output_file=str(out_mp4),
    duration_s=120 / 59.94005994,
    video_width=3840,
    video_height=2160,
    start_dt_utc=telemetry.start_dt_utc,
    tz_offset_hours=2.0,
    speed_samples=telemetry.speed_samples,
    track_samples=telemetry.track_samples,
    alt_samples=telemetry.alt_samples,
    iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples,
    temperature_samples=telemetry.temperature_samples,
    font_path="",
    layout=layout,
    field_samples=fit_data,
    fit_data=fit_data,
    gps_track=gps_track,
    target_fps=59.94005994,
    video_bitrate="40M",
    quality="speed",
)
t1 = time.perf_counter()
print(f"GUI Smoke Render completed: ok={ok}, wall_time={t1-t0:.3f}s")
