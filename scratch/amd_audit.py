"""AMD ETAP 1 Audit Diagnostic Script.

Measures precise timings for TeleM on AMD Ryzen 5 5500U + Radeon iGPU.
Does NOT modify application architecture.
"""

from __future__ import annotations

import json
import os
import sys
import time
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Add workspace to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.benchmark import BenchmarkTracker
from src.ffmpeg.detection import detect_gpu_decoder, detect_best_encoder, _test_encoder, _test_hwaccel
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
from src.indicators.compositor import compose_overlay
from src.indicators.gpu_compositor import GpuCompositor

VIDEO_PATH = Path("Video/GX020079.mp4").resolve()
JSON_PATH = Path("Video/GX020079.json").resolve()
OUTPUT_DIR = Path("scratch/output").resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_test_data():
    print(f"[AUDIT] Loading video and telemetry data from {VIDEO_PATH}...")
    if JSON_PATH.exists():
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
    else:
        print("[AUDIT] Parsing GPMF from video...")
        raw_json = gpmf_to_full_json(VIDEO_PATH)
        records = raw_json

    speed_samples = extract_speed_samples(records)
    track_samples = extract_track_samples(records)
    alt_samples = extract_altitude_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    start_dt_utc = find_gps_anchor(records)

    with open("def_layout.json", "r", encoding="utf-8") as f:
        layout = json.load(f)

    field_samples = {}

    return {
        "video_path": str(VIDEO_PATH),
        "records": records,
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temp_samples": temp_samples,
        "start_dt_utc": start_dt_utc,
        "layout": layout,
        "field_samples": field_samples,
    }

def run_300_frame_export_test(data, mode="STANDARD", encoder_override=None, output_filename="export_test.mp4"):
    out_file = str(OUTPUT_DIR / output_filename)
    if os.path.exists(out_file):
        os.remove(out_file)

    layout = json.loads(json.dumps(data["layout"])) # deep copy
    if mode == "NO_HUD":
        layout["indicators"] = {}
        layout["custom_texts"] = []

    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
    encoder = encoder_override or detect_best_encoder(ffmpeg_exe)

    bt = BenchmarkTracker.get_instance()
    bt.reset()
    bt.enable(True)

    # Render exactly 300 frames (10s @ 30 FPS)

    # Render exactly 300 frames (10s @ 30 FPS)
    duration_s = 10.0
    start_t = time.perf_counter()

    piped_frames = stream_overlay_to_ffmpeg(
        ffmpeg_exe=ffmpeg_exe,
        input_files=[data["video_path"]],
        output_file=out_file,
        duration_s=duration_s,
        start_dt_utc=data["start_dt_utc"],
        tz_offset_hours=0.0,
        speed_samples=data["speed_samples"],
        track_samples=data["track_samples"],
        alt_samples=data["alt_samples"],
        font_path="Arial",
        layout=layout,
        field_samples=data["field_samples"],
        target_fps=30.0,
        update_rate_step=1,
        workers=max(1, (os.cpu_count() or 1) - 1),
        iso_samples=data["iso_samples"],
        exposure_samples=data["exposure_samples"],
        temperature_samples=data["temp_samples"],
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
    fps = piped_frames / elapsed if elapsed > 0 else 0
    summary = bt.get_summary()

    return {
        "mode": mode,
        "encoder": encoder,
        "frames": piped_frames,
        "elapsed_s": elapsed,
        "sustained_fps": fps,
        "benchmark_summary": summary,
    }

if __name__ == "__main__":
    print("=== AMD ETAP 1 Audit Runner ===")
    data = load_test_data()

    print("\n--- Running Standard AMD AMF 300 Frame Export Test ---")
    res_std = run_300_frame_export_test(data, mode="STANDARD", output_filename="amd_amf_300.mp4")
    print(f"Standard AMD Export FPS: {res_std['sustained_fps']:.2f}")

    print("\n--- Running NO HUD 300 Frame Export Test ---")
    res_nohud = run_300_frame_export_test(data, mode="NO_HUD", output_filename="amd_nohud_300.mp4")
    print(f"NO HUD Export FPS: {res_nohud['sustained_fps']:.2f}")

    print("\n--- Running CPU Encoder (libx265) Baseline 300 Frame Export Test ---")
    res_cpu = run_300_frame_export_test(data, mode="STANDARD", encoder_override="cpu", output_filename="cpu_x265_300.mp4")
    print(f"CPU Export FPS: {res_cpu['sustained_fps']:.2f}")

    print("\n=== Benchmark Results Summary ===")
    print("Standard AMF:", res_std)
    print("NO HUD:", res_nohud)
    print("CPU x265:", res_cpu)
