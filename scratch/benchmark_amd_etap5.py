"""Benchmark script for TeleM AMD ETAP 5.
Measures sustained export FPS for SUB-WINDOW HUD, NORMAL HUD, and MAX HUD over 300 frames.
"""

from __future__ import annotations

import json
import os
import sys
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone

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

def run_benchmark(mode_name: str, layout_dict: dict, duration_s: float = 10.0):
    print(f"\n================ BENCHMARK: {mode_name} ({duration_s}s = {int(duration_s*30)} frames) ================")

    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
    out_dir = Path("scratch/benchmark_results").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"benchmark_{mode_name.lower().replace(' ', '_')}.mp4"
    if out_file.exists():
        try: out_file.unlink()
        except Exception: pass

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

    start_t = time.perf_counter()

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
        layout=layout_dict,
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

    print(f"[{mode_name}] Processed {total_frames} frames in {elapsed:.2f}s -> {fps:.2f} FPS")
    return fps, elapsed, total_frames

if __name__ == "__main__":
    with open("def_layout.json", "r", encoding="utf-8") as f:
        normal_layout = json.load(f)

    # 1. SUB-WINDOW HUD (only bottom cluster / time block enabled)
    subwindow_layout = json.load(open("def_layout.json", "r", encoding="utf-8"))
    for k, v in subwindow_layout.get("indicators", {}).items():
        if isinstance(v, dict) and k not in ("time_block", "fit_enhanced_speed_text"):
            v["enabled"] = False

    # 2. MAX HUD (all indicators enabled)
    max_layout = json.load(open("def_layout.json", "r", encoding="utf-8"))
    for k, v in max_layout.get("indicators", {}).items():
        if isinstance(v, dict):
            v["enabled"] = True

    fps_sub, _, _ = run_benchmark("SUB-WINDOW HUD", subwindow_layout, duration_s=10.0)
    fps_norm, _, _ = run_benchmark("NORMAL HUD", normal_layout, duration_s=10.0)
    fps_max, _, _ = run_benchmark("MAX HUD", max_layout, duration_s=10.0)

    print("\n================ SUMMARY BENCHMARK RESULTS ================")
    print(f"SUB-WINDOW HUD : {fps_sub:.2f} FPS")
    print(f"NORMAL HUD     : {fps_norm:.2f} FPS")
    print(f"MAX HUD        : {fps_max:.2f} FPS")
    print("===========================================================")
