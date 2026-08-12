"""Script to compare rendered output frames between Golden Reference (Full 4K RGBA overlay) and AMD Multi-Region overlay.
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
    out_dir = Path("scratch/visual_compare").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Render Golden Reference (Full 4K Overlay using CPU / Software encoding)
    ref_mp4 = out_dir / "ref_nvidia_style.mp4"
    if not ref_mp4.exists() or ref_mp4.stat().st_size == 0:
        print("Rendering Golden Reference (Standard Full 4K Overlay)...")
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
            container_rotation=0,
            overlay_w=3840,
            overlay_h=2160,
            render_w=3840,
            render_h=2160,
        )

    # 2. Render AMD Multi-Region Atlas Pipeline
    amd_mp4 = out_dir / "amd_multi_region.mp4"
    if amd_mp4.exists(): amd_mp4.unlink()

    print("Rendering AMD Multi-Region Atlas Overlay...")
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
        container_rotation=0,
        overlay_w=3840,
        overlay_h=2160,
        render_w=3840,
        render_h=2160,
    )

    # 3. Extract test frames at frame 15, 30, 45 and compare
    test_frames = [15, 30, 45]
    all_match = True
    print("\n================ VISUAL COMPARISON RESULTS ================")
    for f in test_frames:
        ref_png = str(out_dir / f"ref_frame_{f}.png")
        amd_png = str(out_dir / f"amd_frame_{f}.png")
        extract_frame_from_video(str(ref_mp4), f, ref_png)
        extract_frame_from_video(str(amd_mp4), f, amd_png)

        img_ref = np.array(Image.open(ref_png))
        img_amd = np.array(Image.open(amd_png))

        diff = np.abs(img_ref.astype(np.int16) - img_amd.astype(np.int16))
        max_diff = np.max(diff)
        mean_diff = np.mean(diff)

        # Save diff image
        diff_img = Image.fromarray(diff.astype(np.uint8))
        diff_img.save(str(out_dir / f"diff_frame_{f}.png"))

        print(f"Frame {f:02d}: Max Pixel Diff = {max_diff}, Mean Diff = {mean_diff:.4f}")
        if mean_diff > 5.0:  # Allow minor video encoding compression artifacts
            all_match = False

    print("-----------------------------------------------------------")
    if all_match:
        print("VISUAL MATCH: YES")
    else:
        print("VISUAL MATCH: NO")
    print("===========================================================")

if __name__ == "__main__":
    main()
