import os
import sys
import json
import time
sys.path.insert(0, os.path.abspath("."))
from datetime import datetime
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

video_path = os.path.abspath("Video/GX020079.mp4")
output_mp4 = os.path.abspath("Video/GX020079_etap3c_100f.mp4")
layout_path = os.path.abspath("def_layout.json")

with open(layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

font_path = os.path.abspath("include/fonts/Roboto-Bold.ttf")

print("=================================================================")
print("  TeleM — AMD ETAP 3C: 100 REAL FRAMES TEST                      ")
print("=================================================================")

t0 = time.time()
success = export_amd_native_d3d11(
    ffmpeg_exe=r"c:\tools\ffmpeg.exe",
    input_files=[video_path],
    output_file=output_mp4,
    duration_s=100.0 / 29.97,
    video_width=3840,
    video_height=2160,
    start_dt_utc=datetime.now(),
    tz_offset_hours=2.0,
    speed_samples=[],
    track_samples=[],
    alt_samples=[],
    font_path=font_path,
    layout=layout,
    field_samples={},
    target_fps=29.97
)
t1 = time.time()

elapsed = t1 - t0
fps = 100.0 / elapsed if elapsed > 0 else 0
print(f"\n[TEST 100 FRAMES RESULT] Success: {success}")
print(f"Wall-clock elapsed time: {elapsed:.2f} s ({fps:.2f} FPS)")
print(f"Output MP4 exists: {os.path.exists(output_mp4)} ({os.path.getsize(output_mp4) if os.path.exists(output_mp4) else 0} bytes)")
