"""Test canvas scaling with overlay_w=1920 and render_w=3840 (4K export).
"""

from __future__ import annotations

import json
import os
import sys
import shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

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

def extract_frame_from_video(video_path: str, frame_num: int, output_png: str):
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-ss", f"{frame_num / 30.0:.3f}",
        "-i", video_path, "-vframes", "1", output_png
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

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
    out_dir = Path("scratch/visual_compare_scale").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Render Golden Reference (CPU 4K Overlay, overlay_w=3840, render_w=3840)
    ref_mp4 = out_dir / "ref_scaled_4k.mp4"
    if not ref_mp4.exists() or ref_mp4.stat().st_size == 0:
        print("Rendering Golden Reference (4K)...")
        stream_overlay_to_ffmpeg(
            ffmpeg_exe=ffmpeg_exe,
            input_files=[str(VIDEO_PATH)],
            output_file=str(ref_mp4),
            duration_s=2.0,
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
            workers=4,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temp_samples,
            encoder="cpu",
            gpu=0,
            resolution_name="4k",
            video_bitrate="25M",
            rotation_degrees=0,
            container_rotation=180,
            overlay_w=3840,
            overlay_h=2160,
            render_w=3840,
            render_h=2160,
        )

    # 2. AMD Multi-Region with 1080p overlay scaled to 4K (overlay_w=1920, render_w=3840)
    amd_mp4 = out_dir / "amd_scaled_1080p_to_4k.mp4"
    if amd_mp4.exists():
        try: amd_mp4.unlink()
        except Exception: pass

    print("Rendering AMD Multi-Region (1080p overlay -> 4K render)...")
    stream_overlay_to_ffmpeg(
        ffmpeg_exe=ffmpeg_exe,
        input_files=[str(VIDEO_PATH)],
        output_file=str(amd_mp4),
        duration_s=2.0,
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
        workers=4,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        encoder="amd",
        gpu=0,
        resolution_name="4k",
        video_bitrate="25M",
        rotation_degrees=0,
        container_rotation=180,
        overlay_w=1920,
        overlay_h=1080,
        render_w=3840,
        render_h=2160,
    )

    ref_png = str(out_dir / "ref_frame_15.png")
    amd_png = str(out_dir / "amd_frame_15.png")
    extract_frame_from_video(str(ref_mp4), 15, ref_png)
    extract_frame_from_video(str(amd_mp4), 15, amd_png)

    img_ref = np.array(Image.open(ref_png))
    img_amd = np.array(Image.open(amd_png))

    diff = np.abs(img_ref.astype(np.int16) - img_amd.astype(np.int16))
    max_diff = np.max(diff)
    mean_diff = np.mean(diff)

    print("\n================ SCALED OVERLAY VISUAL COMPARISON ================")
    print(f"Frame 15: Max Pixel Diff = {max_diff}, Mean Diff = {mean_diff:.4f}")
    if mean_diff < 15.0:  # Allow bilinear scaling differences between 1080p and 4K
        print("VISUAL MATCH: YES")
    else:
        print("VISUAL MATCH: NO")
    print("==================================================================")

if __name__ == "__main__":
    main()
