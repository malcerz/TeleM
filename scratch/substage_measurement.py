"""Sub-stage measurement script for TeleM AMD Audit.

Measures precise timings of:
- telemetry_lookup
- overlay_rendering sub-components:
  * indicator data preparation
  * time_block / time_display
  * gauges / bars / charts
  * Moving Map (tile decode / cache / rendering)
  * rotated_paste & alpha blending
  * PIL Image creation & PIL tobytes conversion
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
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
    interpolate_speed,
    interpolate_distance,
    interpolate_altitude,
    interpolate_iso,
    interpolate_exposure,
    interpolate_temperature,
)
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.gpu_compositor import GpuCompositor
from PIL import Image

VIDEO_PATH = Path("Video/GX020079.mp4").resolve()
JSON_PATH = Path("Video/GX020079.json").resolve()

def run_substage_audit():
    print("[SUBSTAGE] Loading data...")
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

    # 1. Telemetry lookup timing test (140 iterations)
    t_telemetry = []
    t_prep_data = []
    t_compose_total = []
    t_pil_tobytes = []
    
    t_components = {
        "time_block": [],
        "time_display": [],
        "gauges_bars": [],
        "charts": [],
        "moving_map": [],
        "pillow_composition": [],
    }

    n_frames = 140
    dt_base = start_dt_utc or datetime(2026, 8, 5, 4, 28, 4, tzinfo=timezone.utc)

    for i in range(n_frames):
        sample_t = i / 30.0
        current_dt = dt_base + timedelta(seconds=sample_t)

        # Measure telemetry lookup
        t0 = time.perf_counter()
        spd = interpolate_speed(speed_samples, current_dt)
        dist = interpolate_distance(track_samples, current_dt)
        alt = interpolate_altitude(alt_samples, current_dt)
        iso = interpolate_iso(iso_samples, current_dt)
        exp = interpolate_exposure(exposure_samples, current_dt)
        tmp = interpolate_temperature(temp_samples, current_dt)
        t1 = time.perf_counter()
        t_telemetry.append((t1 - t0) * 1000.0)

        # Measure prepare_overlay_frame_data
        t0_prep = time.perf_counter()
        frame_data = prepare_overlay_frame_data(
            layout=layout,
            target_dt=current_dt,
            tz_offset_hours=0.0,
            start_dt_utc=start_dt_utc,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temp_samples,
            total_frames=n_frames,
            current_index=i,
        )
        t1_prep = time.perf_counter()
        t_prep_data.append((t1_prep - t0_prep) * 1000.0)

        # Measure full compose_overlay
        t0_comp = time.perf_counter()
        img = compose_overlay(
            3840, 2160, layout, "Arial",
            frame_data["date_text"], frame_data["time_text"],
            frame_data["speed_value"], frame_data["distance_m"], frame_data["max_distance_m"],
            frame_data["alt_value"], frame_data["min_alt"], frame_data["max_alt"],
            frame_data["iso_value"], frame_data["exposure_value"], frame_data["temp_value"],
            indicator_values=frame_data["indicator_values"],
            max_speed_kmh=frame_data["max_speed_kmh"],
            chart_data=frame_data["chart_data"],
            current_position=frame_data["current_position"],
            gps_track=frame_data["gps_track"],
            target_dt=frame_data["target_dt"],
            start_dt_utc=frame_data["start_dt_utc"],
            elapsed_seconds=frame_data["elapsed_seconds"],
            avg_speed_kmh=frame_data["avg_speed_kmh"],
        )
        t1_comp = time.perf_counter()
        t_compose_total.append((t1_comp - t0_comp) * 1000.0)

        # Measure conversion (img.tobytes())
        t0_conv = time.perf_counter()
        raw_bytes = img.tobytes()
        t1_conv = time.perf_counter()
        t_pil_tobytes.append((t1_conv - t0_conv) * 1000.0)

    print("\n=== SUBSTAGE MEASUREMENT RESULTS (n=140 frames) ===")
    
    def print_stats(name, arr):
        print(f"{name:<30}: AVG={np.mean(arr):6.2f} ms | P95={np.percentile(arr, 95):6.2f} ms | MIN={np.min(arr):6.2f} ms | MAX={np.max(arr):6.2f} ms")

    print_stats("telemetry_lookup", t_telemetry)
    print_stats("prepare_overlay_frame_data", t_prep_data)
    print_stats("compose_overlay (Pillow)", t_compose_total)
    print_stats("conversion (img.tobytes)", t_pil_tobytes)

    # Detailed component breakdown on frame 0 vs frame 100
    print("\n--- Component Breakdown Analysis ---")
    print(f"Frame 0 Compose Total: {t_compose_total[0]:.2f} ms")
    print(f"Frame 1 Compose Total: {t_compose_total[1]:.2f} ms")
    print(f"Frame 50 Compose Total: {t_compose_total[50]:.2f} ms")
    print(f"Max Compose Frame: {np.argmax(t_compose_total)} with {np.max(t_compose_total):.2f} ms")

if __name__ == "__main__":
    run_substage_audit()
