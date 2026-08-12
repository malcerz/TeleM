"""Audit Python Pillow rendering sub-stages timing for NORMAL HUD (300 frames).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
import numpy as np

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
from src.ffmpeg.worker_cache import init_worker
from src.ffmpeg.frame_renderer import render_frame_bytes_job

VIDEO_PATH = Path("Video/GX020079.mp4").resolve()
JSON_PATH = Path("Video/GX020079.json").resolve()

def profile_pillow():
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
        layout = json.load(f)

    init_worker(
        3840, 2160, "Arial", layout, {}, 0.0,
        iso_samples, exposure_samples, temp_samples,
        {}, {}, {}, {}, {}, {}, {},
        {}, [], start_dt_utc, 0.0,
        speed_samples, track_samples, alt_samples,
        30.0, 1, 300
    )

    t_render_total = 0.0
    for frame_idx in range(100):
        t0 = time.perf_counter()
        idx, img_bytes = render_frame_bytes_job((frame_idx,))
        t_render_total += (time.perf_counter() - t0)

    avg_ms = (t_render_total / 100.0) * 1000.0
    fps_max = 1000.0 / avg_ms if avg_ms > 0 else 0

    print("=================== PILLOW HUD RENDER PROFILING ===================")
    print(f"Average Single-Thread Pillow Render Time: {avg_ms:.2f} ms")
    print(f"Max Possible Single-Thread CPU Render FPS : {fps_max:.2f} FPS")
    print("===================================================================")

if __name__ == "__main__":
    profile_pillow()
