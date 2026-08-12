"""Test full end-to-end Multi-Region HUD Atlas pipeline for NORMAL HUD (300 frames).
"""

from __future__ import annotations

import json
import os
import sys
import time
import shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.telemetry_gpmf_new import gpmf_to_full_json
from src.telemetry_extract import (
    extract_speed_samples,
    extract_track_samples,
    extract_altitude_samples,
    extract_iso_samples,
    extract_exposure_samples,
    extract_temperature_samples,
    find_gps_anchor,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

VIDEO_PATH = Path("Video/GX020079.mp4").resolve()
JSON_PATH = Path("Video/GX020079.json").resolve()

def main():
    if JSON_PATH.exists():
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
    else:
        records = gpmf_to_full_json(VIDEO_PATH)

    speed_samples = extract_speed_samples(records)
    track_samples = extract_track_samples(records)
    alt_samples = extract_altitude_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    start_dt_utc = find_gps_anchor(records)

    with open("def_layout.json", "r", encoding="utf-8") as f:
        normal_layout = json.load(f)

    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
    out_file = Path("scratch/output/test_atlas_normal_300.mp4").resolve()
    if out_file.exists():
        out_file.unlink()

    print("\n--- Running Multi-Region Atlas Test: NORMAL HUD (300 frames) ---")
    t0 = time.perf_counter()
    piped_frames = stream_overlay_to_ffmpeg(
        ffmpeg_exe=ffmpeg_exe,
        input_files=[str(VIDEO_PATH)],
        output_file=str(out_file),
        duration_s=10.0,
        start_dt_utc=start_dt_utc,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="Arial",
        layout=normal_layout,
        field_samples={},
        target_fps=30.0,
        update_rate_step=1,
        workers=max(1, (os.cpu_count() or 1) - 1),
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        encoder="amd",
        gpu=0,
        resolution_name="4k",
        video_bitrate="25M",
        rotation_degrees=0,
        container_rotation=0,
        overlay_w=3840,
        overlay_h=2160,
        render_w=3840,
        render_h=2160,
    )
    dt = time.perf_counter() - t0
    fps = piped_frames / dt if dt > 0 else 0
    print(f"NORMAL HUD Export Time: {dt:.2f} s ({fps:.2f} FPS)")
    print(f"Output File Size: {out_file.stat().st_size / (1024*1024):.1f} MB")

if __name__ == "__main__":
    main()
