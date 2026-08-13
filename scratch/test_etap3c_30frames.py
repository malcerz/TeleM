import os
import sys
import json
import time
sys.path.insert(0, os.path.abspath("."))
from datetime import datetime
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

video_path = os.path.abspath("Video/GX020079.mp4")
output_mp4 = os.path.abspath("Video/GX020079_etap3c_30f.mp4")
layout_path = os.path.abspath("def_layout.json")

with open(layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

font_path = os.path.abspath("include/fonts/Roboto-Bold.ttf")

print("=================================================================")
print("  TeleM — AMD ETAP 3C: 31 REAL FRAMES TEST                       ")
print("=================================================================")

success = export_amd_native_d3d11(
    ffmpeg_exe=r"c:\tools\ffmpeg.exe",
    input_files=[video_path],
    output_file=output_mp4,
    duration_s=31.0 / 29.97,
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

print(f"\n[TEST RESULT] export_amd_native_d3d11 success: {success}")
print("\n[CHECKPOINTS STATUS]:")
for fn in [
    "01_python_hud.png",
    "02_buffer_sent_to_dll.png",
    "03_d3d11_hud_texture.png",
    "04_videoprocessor_output.png",
    "05_final_encoded_frame.png"
]:
    exists = os.path.exists(fn)
    size = os.path.getsize(fn) if exists else 0
    print(f"  - {fn}: {'PASS' if exists and size > 0 else 'FAIL'} ({size} bytes)")
