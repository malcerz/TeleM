import sys, os, subprocess
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

def main():
    v_file = Path('Video/GX020079.mp4')
    fit_file = Path('Video/Morning_Ride.fit')
    
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    anchor_dt = find_gps_anchor(records)
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

    test_layout = normalize_layout(None, 1920, 1080)
    for k, v in test_layout["indicators"].items():
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
            v["enabled"] = False

    out_bbox = Path('scratch/parity_bbox.mp4')
    out_full = Path('scratch/parity_full.mp4')

    print("\n--- 1. Rendering SAME layout with HUD Bbox (1712x488) ---")
    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_bbox),
        duration_s=2.0,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=test_layout,
        field_samples={},
        target_fps=29.97,
        update_rate_step=1,
        workers=4,
        encoder="nv",
        gpu=0,
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        rotation_degrees=0,
        container_rotation=0,
        overlay_w=1920,
        overlay_h=1080,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
    )

    # Force full frame by temporarily passing overlay without bbox or layout covering all
    print("\n--- 2. Rendering SAME layout with Full Frame (Forced 1920x1080) ---")
    # To force full frame on test_layout, we can add a dummy invisible indicator at 0,0 and 100,100 or set fallback threshold
    full_test_layout = normalize_layout(None, 1920, 1080)
    for k, v in full_test_layout["indicators"].items():
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
            v["enabled"] = False
    # Add dummy 0,0 and 100,100 indicators with opacity 0 or disabled=False but empty text
    full_test_layout["custom_texts"].append({"enabled": True, "text": " ", "x": 0.0, "y": 0.0, "font_size": 1.0})
    full_test_layout["custom_texts"].append({"enabled": True, "text": " ", "x": 99.0, "y": 99.0, "font_size": 1.0})

    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_full),
        duration_s=2.0,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=full_test_layout,
        field_samples={},
        target_fps=29.97,
        update_rate_step=1,
        workers=4,
        encoder="nv",
        gpu=0,
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        rotation_degrees=0,
        container_rotation=0,
        overlay_w=1920,
        overlay_h=1080,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
    )

    frame_bbox_png = Path('scratch/frame_bbox.png')
    frame_full_png = Path('scratch/frame_full.png')
    subprocess.run(["ffmpeg", "-y", "-ss", "1.0", "-i", str(out_bbox), "-vframes", "1", str(frame_bbox_png)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-ss", "1.0", "-i", str(out_full), "-vframes", "1", str(frame_full_png)], check=True, capture_output=True)

    arr_bbox = np.asarray(Image.open(frame_bbox_png))
    arr_full = np.asarray(Image.open(frame_full_png))

    diff = np.abs(arr_bbox.astype(np.int32) - arr_full.astype(np.int32))
    max_diff = int(np.max(diff))
    mean_diff = float(np.mean(diff))
    diff_pixels = int(np.count_nonzero(diff.any(axis=-1)))
    total_pixels = arr_bbox.shape[0] * arr_bbox.shape[1]

    print(f"\n[TRUE PARITY METRICS FOR FULL 4K FRAME (3840x2160)]")
    print(f"  Max channel diff: {max_diff}")
    print(f"  Mean absolute diff: {mean_diff:.6f}")
    print(f"  Differing pixels: {diff_pixels} / {total_pixels} ({diff_pixels / total_pixels * 100:.3f}%)")
    print(f"  Pixel Parity Result: {'PASSED (Pixel-Exact match within NVENC chroma precision)' if max_diff <= 4 else 'FAILED'}")

if __name__ == '__main__':
    main()
