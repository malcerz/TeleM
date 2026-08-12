"""Proof-of-Concept script for TeleM AMD ETAP 6: D3D11 / OpenCL GPU-Resident HUD Compositor.
Compares Software CPU Overlay vs Hardware GPU Overlay (overlay_opencl).
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

def run_poc_test(desc: str, mode: str, use_gpu_compositor: bool = False, num_frames: int = 150):
    print(f"\n================ PoC TEST: {desc} ({num_frames} frames) ================")

    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
    out_dir = Path("scratch/poc_results").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"poc_{mode.lower().replace(' ', '_')}_{'gpu' if use_gpu_compositor else 'sw'}.mp4"
    if out_file.exists():
        try: out_file.unlink()
        except Exception: pass

    with open("def_layout.json", "r", encoding="utf-8") as f:
        layout = json.load(f)

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

    duration_s = num_frames / 30.0
    start_t = time.perf_counter()

    # Pass use_gpu_compositor flag through custom layout property if supported
    layout["_use_gpu_compositor"] = use_gpu_compositor

    total_frames = stream_overlay_to_ffmpeg(
        ffmpeg_exe=ffmpeg_exe,
        input_files=[str(VIDEO_PATH)],
        output_file=str(out_file),
        duration_s=duration_s,
        start_dt_utc=start_dt_utc,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="Arial",
        layout=layout,
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

    elapsed = time.perf_counter() - start_t
    fps = total_frames / elapsed if elapsed > 0 else 0

    print(f"[{desc}] Processed {total_frames} frames in {elapsed:.2f}s -> {fps:.2f} FPS")
    return fps, elapsed

if __name__ == "__main__":
    fps_sw, _ = run_poc_test("Software CPU Overlay Baseline", "normal", use_gpu_compositor=False, num_frames=150)
    fps_gpu, _ = run_poc_test("Hardware GPU Compositor (PoC)", "normal", use_gpu_compositor=True, num_frames=150)

    print("\n================ PoC COMPARISON SUMMARY ================")
    print(f"Software CPU Overlay  : {fps_sw:.2f} FPS")
    print(f"Hardware GPU Compositor: {fps_gpu:.2f} FPS")
    print(f"Speedup              : {((fps_gpu - fps_sw)/fps_sw*100.0):+.1f}%")
    print("========================================================")
