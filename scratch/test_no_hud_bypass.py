"""Test smart NO HUD direct GPU bypass in TeleM streaming pipeline.
"""

from __future__ import annotations

import json
import os
import sys
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ffmpeg.detection import detect_best_encoder
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.telemetry_gpmf_new import gpmf_to_full_json
from src.telemetry_extract import find_gps_anchor

VIDEO_PATH = Path("Video/GX020079.mp4").resolve()
OUT_FILE = Path("scratch/output/test_no_hud_bypass_out.mp4").resolve()
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

def test_bypass():
    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
    encoder = "amd"
    nohud_layout = {"indicators": {}, "custom_texts": []}

    if OUT_FILE.exists():
        OUT_FILE.unlink()

    print("[TEST] Running NO HUD export test with direct GPU bypass...")
    start_t = time.perf_counter()

    piped_frames = stream_overlay_to_ffmpeg(
        ffmpeg_exe=ffmpeg_exe,
        input_files=[str(VIDEO_PATH)],
        output_file=str(OUT_FILE),
        duration_s=10.0, # 300 frames
        start_dt_utc=datetime(2026, 8, 5, 4, 28, 4, tzinfo=timezone.utc),
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="Arial",
        layout=nohud_layout,
        field_samples={},
        target_fps=30.0,
        update_rate_step=1,
        workers=1,
        encoder=encoder,
        gpu=0,
        resolution_name="source",
        video_bitrate="25M",
        rotation_degrees=0,
        container_rotation=0,
        overlay_w=3840,
        overlay_h=2160,
        render_w=3840,
        render_h=2160,
    )

    elapsed = time.perf_counter() - start_t
    fps = piped_frames / elapsed if elapsed > 0 else 0

    print("\n=== NO HUD DIRECT GPU BYPASS RESULT ===")
    print(f"Piped Frames: {piped_frames}")
    print(f"Total Time: {elapsed:.2f} s")
    print(f"Sustained Export FPS: {fps:.2f} FPS")
    print(f"Output Size: {OUT_FILE.stat().st_size / (1024*1024):.1f} MB")

if __name__ == "__main__":
    test_bypass()
