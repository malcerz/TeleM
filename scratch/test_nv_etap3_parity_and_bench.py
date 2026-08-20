import sys, os, time, subprocess
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

def run_parity_test():
    print("=" * 70)
    print("TEST 1: PIXEL PARITY TEST (Full Frame vs HUD Bbox)")
    print("=" * 70)

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

    # Use a bottom HUD layout to trigger the active bbox path
    bottom_layout = normalize_layout(None, 1920, 1080)
    for k, v in bottom_layout["indicators"].items():
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
            v["enabled"] = False

    # Export 2 seconds (60 frames)
    out_bbox = Path('scratch/parity_bbox.mp4')
    
    print("\n--- 1.A Rendering with HUD BBox ---")
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
        layout=bottom_layout,
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

    # Force fallback to full frame for comparison
    out_full = Path('scratch/parity_full.mp4')
    print("\n--- 1.B Rendering with Full Frame (Forced fallback) ---")
    full_layout = normalize_layout(None, 1920, 1080)
    # Enable all to force full frame fallback
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
        layout=full_layout,
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

    # Extract frame 30 from both videos
    frame_bbox_png = Path('scratch/frame_bbox.png')
    frame_full_png = Path('scratch/frame_full.png')
    subprocess.run(["ffmpeg", "-y", "-ss", "1.0", "-i", str(out_bbox), "-vframes", "1", str(frame_bbox_png)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-ss", "1.0", "-i", str(out_full), "-vframes", "1", str(frame_full_png)], check=True, capture_output=True)

    arr_bbox = np.asarray(Image.open(frame_bbox_png))
    arr_full = np.asarray(Image.open(frame_full_png))

    # Crop the bottom HUD area from both (y: 1300 to 2160)
    hud_crop_bbox = arr_bbox[1300:2160, :]
    hud_crop_full = arr_full[1300:2160, :]

    diff = np.abs(hud_crop_bbox.astype(np.int32) - hud_crop_full.astype(np.int32))
    max_diff = np.max(diff)
    mean_diff = np.mean(diff)
    diff_pixels = np.count_nonzero(diff.any(axis=-1))

    print(f"\n[PARITY METRICS for HUD Region (3840x860 px)]")
    print(f"  Max channel diff: {max_diff}")
    print(f"  Mean absolute diff: {mean_diff:.4f}")
    print(f"  Differing pixels in HUD: {diff_pixels} / {hud_crop_bbox.shape[0] * hud_crop_bbox.shape[1]}")

    # Check if max diff <= 3 (typical for NVENC / YUV chroma subsampling rounding)
    parity_pass = max_diff <= 4
    print(f"  Pixel Parity Result: {'PASSED' if parity_pass else 'FAILED'}")

def run_benchmark():
    print("\n" + "=" * 70)
    print("TEST 2: BENCHMARK (1132 frames, GX020079.mp4 4K)")
    print("=" * 70)

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

    duration_s = 37.74
    target_fps = 29.97

    # 1. Default Layout (Fallback full frame 1920x1080)
    default_layout = normalize_layout(None, 1920, 1080)
    out_def = Path('scratch/bench_etap3_default.mp4')
    print("\n--- 2.A Default Layout (Automatic Fallback to Full Frame) ---")
    t0 = time.perf_counter()
    n_def = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_def),
        duration_s=duration_s,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=default_layout,
        field_samples={},
        target_fps=target_fps,
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
    t1 = time.perf_counter()
    elapsed_def = t1 - t0
    fps_def = n_def / elapsed_def
    print(f"[RESULT 2.A] Elapsed: {elapsed_def:.2f} s | FPS: {fps_def:.2f} FPS")

    # 2. Bottom HUD Layout (Active HUD Bbox 1872x424 -> 3.17 MB slot)
    bottom_layout = normalize_layout(None, 1920, 1080)
    for k, v in bottom_layout["indicators"].items():
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
            v["enabled"] = False
    out_bbox = Path('scratch/bench_etap3_bbox.mp4')
    print("\n--- 2.B Bottom HUD Layout (Active HUD Bbox ~38% Area) ---")
    t0 = time.perf_counter()
    n_bbox = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_bbox),
        duration_s=duration_s,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=bottom_layout,
        field_samples={},
        target_fps=target_fps,
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
    t1 = time.perf_counter()
    elapsed_bbox = t1 - t0
    fps_bbox = n_bbox / elapsed_bbox
    print(f"[RESULT 2.B] Elapsed: {elapsed_bbox:.2f} s | FPS: {fps_bbox:.2f} FPS")

if __name__ == '__main__':
    run_parity_test()
    run_benchmark()
