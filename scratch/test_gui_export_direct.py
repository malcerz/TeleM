import os
import sys
import json
import time
sys.path.insert(0, os.path.abspath("."))

from datetime import datetime
from PySide6.QtWidgets import QApplication
from src.gui.telemetry_manager import TelemetryDataManager
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

app = QApplication(sys.argv)

print("=================================================================")
print("  TeleM — AMD ETAP 3C: REAL PRODUCTION GUI EXPORT TEST          ")
print("=================================================================")

video_path = os.path.abspath("Video/GX020079.mp4")
fit_path = os.path.abspath("Video/Morning_Ride.fit")
output_mp4 = os.path.abspath("Video/GX020079_real_gui_export_3c.mp4")
layout_path = os.path.abspath("def_layout.json")

with open(layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

font_path = os.path.abspath("include/fonts/Roboto-Bold.ttf")

print("[1/3] Loading real TeleM telemetry manager...")
tm = TelemetryDataManager()
tm.load_fit(fit_path)

print("[2/3] Extracting primary telemetry samples...")
speed_samples = tm.speed_samples
track_samples = tm.track_samples
alt_samples = tm.alt_samples
print(f"  - Speed samples: {len(speed_samples)}")
print(f"  - Track samples: {len(track_samples)}")
print(f"  - Alt samples:   {len(alt_samples)}")

print("[3/3] Dispatching to production export_amd_native_d3d11...")
t0 = time.time()
success = export_amd_native_d3d11(
    ffmpeg_exe=r"c:\tools\ffmpeg.exe",
    input_files=[video_path],
    output_file=output_mp4,
    duration_s=37.74, # Full duration of GX020079.mp4!
    video_width=3840,
    video_height=2160,
    start_dt_utc=tm.start_dt_utc,
    tz_offset_hours=2.0,
    speed_samples=speed_samples,
    track_samples=track_samples,
    alt_samples=alt_samples,
    font_path=font_path,
    layout=layout,
    field_samples={},
    target_fps=29.97,
    fit_data=tm.fit_data,
    gps_track=tm.fit_gps_track
)
t1 = time.time()

elapsed = t1 - t0
fps = 1131.0 / elapsed if elapsed > 0 else 0
print("\n=================================================================")
print(f"  REAL GUI EXPORT RESULT: {'SUCCESS' if success else 'FAIL'}")
print(f"  Wall-clock elapsed:     {elapsed:.2f} s ({fps:.2f} FPS)")
print(f"  Output MP4 exists:      {os.path.exists(output_mp4)}")
print(f"  Output MP4 size:        {os.path.getsize(output_mp4) if os.path.exists(output_mp4) else 0} bytes")
print("=================================================================")
