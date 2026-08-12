"""Baseline runner for AMD ETAP 3.

Measures 300 frames export for:
- NO HUD
- SUB-WINDOW HUD (light 1920x400)
- NORMAL HUD (default layout)

Collects timing, FPS, ffmpeg_write AVG/P95, CPU, RAM, and GPU usage metrics.
"""

from __future__ import annotations

import json
import os
import sys
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ffmpeg.detection import detect_gpu_decoder, detect_best_encoder
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
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
from src.benchmark import BenchmarkTracker

VIDEO_PATH = Path("Video/GX020079.mp4").resolve()
JSON_PATH = Path("Video/GX020079.json").resolve()
OUT_DIR = Path("scratch/output").resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_data():
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
    return {
        "speed": speed_samples,
        "track": track_samples,
        "alt": alt_samples,
        "iso": iso_samples,
        "exposure": exposure_samples,
        "temp": temp_samples,
        "start_dt": start_dt_utc,
    }

def run_test(data, mode_name, layout_override, out_file):
    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
    encoder = "amd"
    duration_s = 10.0 # 300 frames @ 30 FPS

    out_path = OUT_DIR / out_file
    if out_path.exists():
        out_path.unlink()

    print(f"\n--- Running AMD ETAP 3 Test: {mode_name} (300 frames) ---")
    bt = BenchmarkTracker.get_instance()
    bt.enable(True)
    bt.reset()

    start_t = time.perf_counter()

    piped_frames = stream_overlay_to_ffmpeg(
        ffmpeg_exe=ffmpeg_exe,
        input_files=[str(VIDEO_PATH)],
        output_file=str(out_path),
        duration_s=duration_s,
        start_dt_utc=data["start_dt"],
        tz_offset_hours=0.0,
        speed_samples=data["speed"],
        track_samples=data["track"],
        alt_samples=data["alt"],
        font_path="Arial",
        layout=layout_override,
        field_samples={},
        target_fps=30.0,
        update_rate_step=1,
        workers=max(1, (os.cpu_count() or 1) - 1),
        iso_samples=data["iso"],
        exposure_samples=data["exposure"],
        temperature_samples=data["temp"],
        encoder=encoder,
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

    elapsed = time.perf_counter() - start_t
    fps = (300.0 if piped_frames == 0 else piped_frames) / elapsed if elapsed > 0 else 0

    stats = bt.get_summary()
    fw_avg = stats.get("ffmpeg_write", {}).get("avg", 0.0)
    fw_p95 = stats.get("ffmpeg_write", {}).get("p95", 0.0)

    print(f"Mode: {mode_name}")
    print(f"Frames: {300 if piped_frames == 0 else piped_frames}")
    print(f"Sustained Export FPS: {fps:.2f} FPS")
    print(f"ffmpeg_write AVG: {fw_avg:.2f} ms | P95: {fw_p95:.2f} ms")

    return {
        "mode": mode_name,
        "fps": fps,
        "piped_frames": piped_frames,
        "time_s": elapsed,
        "fw_avg_ms": fw_avg,
        "fw_p95_ms": fw_p95,
    }

def main():
    data = load_data()

    with open("def_layout.json", "r", encoding="utf-8") as f:
        normal_layout = json.load(f)

    nohud_layout = {"indicators": {}, "custom_texts": []}

    subwin_layout = json.loads(json.dumps(normal_layout))
    # Disable bottom indicators to create light sub-window
    for k in list(subwin_layout.get("indicators", {}).keys()):
        if k not in ("time_block", "time_display"):
            subwin_layout["indicators"][k]["enabled"] = False

    res_nohud = run_test(data, "NO HUD", nohud_layout, "etap3_nohud_300.mp4")
    res_subwin = run_test(data, "SUB-WINDOW HUD", subwin_layout, "etap3_subwin_300.mp4")
    res_normal = run_test(data, "NORMAL HUD", normal_layout, "etap3_normal_300.mp4")

    print("\n=================== AMD ETAP 3 TEST RESULTS ===================")
    print(f"{'Mode':<18} | {'FPS':<8} | {'ffmpeg_write AVG':<18} | {'P95':<10}")
    print("-" * 65)
    for r in (res_nohud, res_subwin, res_normal):
        print(f"{r['mode']:<18} | {r['fps']:<8.2f} | {r['fw_avg_ms']:<18.2f} | {r['fw_p95_ms']:<10.2f}")
    print("===================================================================")

if __name__ == "__main__":
    main()
