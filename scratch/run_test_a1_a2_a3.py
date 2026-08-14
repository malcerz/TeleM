import os
import sys
import json
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath("."))
from datetime import datetime
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

video_path = os.path.abspath("Video/GX020079.mp4")
layout_path = os.path.abspath("def_layout.json")
font_path = os.path.abspath("include/fonts/Roboto-Bold.ttf")

with open(layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

print("=================================================================")
print("  TeleM — AMD ETAP 3C-CORRECTNESS: TESTS A1, A2, A3              ")
print("=================================================================")

# TEST A1: VideoProcessor Stream 0 Only (No HUD)
print("\n--- RUNNING TEST A1 (Stream 0 Only / HUD Disabled) ---")
output_a1 = os.path.abspath("Video/GX020079_test_a1.mp4")
layout_no_hud = dict(layout)
layout_no_hud["indicators"] = {}
layout_no_hud["custom_texts"] = {}

success_a1 = export_amd_native_d3d11(
    ffmpeg_exe=r"c:\tools\ffmpeg.exe",
    input_files=[video_path],
    output_file=output_a1,
    duration_s=31.0 / 29.97,
    video_width=3840,
    video_height=2160,
    start_dt_utc=datetime.now(),
    tz_offset_hours=2.0,
    speed_samples=[],
    track_samples=[],
    alt_samples=[],
    font_path=font_path,
    layout=layout_no_hud,
    field_samples={},
    target_fps=29.97
)

# TEST A2 & A3: Full Exporter Run
print("\n--- RUNNING TEST A2 & A3 (Real HUD + Magenta Checkpoint) ---")
output_a2 = os.path.abspath("Video/GX020079_test_a2.mp4")
success_a2 = export_amd_native_d3d11(
    ffmpeg_exe=r"c:\tools\ffmpeg.exe",
    input_files=[video_path],
    output_file=output_a2,
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

# Analyze Checkpoint Images
print("\n--- ANALYZING CHECKPOINT IMAGES FOR ALPHA AND VISIBILITY ---")
for img_name in ["01_python_hud.png", "02_buffer_sent_to_dll.png", "03_d3d11_hud_texture.png", "04_videoprocessor_output.png", "05_final_encoded_frame.png"]:
    if os.path.exists(img_name):
        im = Image.open(img_name)
        arr = np.array(im)
        print(f"\nImage: {img_name} ({im.size}, mode={im.mode})")
        if arr.ndim == 3 and arr.shape[2] == 4:
            alpha = arr[:, :, 3]
            a_min, a_max = alpha.min(), alpha.max()
            zero_px = (alpha == 0).sum()
            full_px = (alpha == 255).sum()
            sample_px = arr[500, 1000]
            print(f"  - alpha_min: {a_min}, alpha_max: {a_max}")
            print(f"  - alpha_zero_pixels: {zero_px}, alpha_255_pixels: {full_px}")
            print(f"  - sample pixel at (1000, 500) RGBA: {sample_px.tolist()}")
        elif arr.ndim == 3:
            # RGB image
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            sample_px = arr[500, 1000]
            print(f"  - RGB Image. sample pixel at (1000, 500) RGB: {sample_px.tolist()}")
            print(f"  - Mean RGB intensity: R={r.mean():.1f}, G={g.mean():.1f}, B={b.mean():.1f}")
