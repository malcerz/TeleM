"""Test script for HUD sub-window pipeline.
"""

from __future__ import annotations

import json
import os
import sys
import time
import shutil
import subprocess
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
)
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data

VIDEO_PATH = Path("Video/GX020079.mp4").resolve()
JSON_PATH = Path("Video/GX020079.json").resolve()

def get_hud_bbox(img, bboxes, canvas_w=3840, canvas_h=2160, pad=20):
    if not bboxes:
        return 0, 0, 2, 2
    min_x = min(bx for bx, by, bw, bh in bboxes.values())
    min_y = min(by for bx, by, bw, bh in bboxes.values())
    max_x = max(bx + bw for bx, by, bw, bh in bboxes.values())
    max_y = max(by + bh for bx, by, bw, bh in bboxes.values())

    crop_x = max(0, min_x - pad)
    crop_y = max(0, min_y - pad)
    crop_w = min(canvas_w - crop_x, (max_x + pad) - crop_x)
    crop_h = min(canvas_h - crop_y, (max_y + pad) - crop_y)

    if crop_x % 2 != 0: crop_x -= 1
    if crop_y % 2 != 0: crop_y -= 1
    if crop_w % 2 != 0: crop_w += 1
    if crop_h % 2 != 0: crop_h += 1

    return crop_x, crop_y, max(2, crop_w), max(2, crop_h)

def test_subwindow():
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

    dt = start_dt_utc or datetime(2026, 8, 5, 4, 28, 4, tzinfo=timezone.utc)
    fd = prepare_overlay_frame_data(
        layout=layout, target_dt=dt, tz_offset_hours=0.0,
        start_dt_utc=start_dt_utc, speed_samples=speed_samples,
        track_samples=track_samples, alt_samples=alt_samples,
        iso_samples=iso_samples, exposure_samples=exposure_samples,
        temperature_samples=temp_samples, total_frames=100, current_index=0,
    )

    bboxes = {}
    img = compose_overlay(
        3840, 2160, layout, "Arial",
        fd["date_text"], fd["time_text"],
        fd["speed_value"], fd["distance_m"], fd["max_distance_m"],
        fd["alt_value"], fd["min_alt"], fd["max_alt"],
        fd["iso_value"], fd["exposure_value"], fd["temp_value"],
        indicator_values=fd["indicator_values"],
        max_speed_kmh=fd["max_speed_kmh"],
        _bboxes=bboxes,
        chart_data=fd["chart_data"],
        current_position=fd["current_position"],
        gps_track=fd["gps_track"],
        target_dt=fd["target_dt"],
        start_dt_utc=fd["start_dt_utc"],
        elapsed_seconds=fd["elapsed_seconds"],
        avg_speed_kmh=fd["avg_speed_kmh"],
    )

    cx, cy, cw, ch = get_hud_bbox(img, bboxes)
    print(f"Full Canvas: 3840x2160 ({3840*2160*4 / 1024 / 1024:.1f} MB)")
    print(f"HUD Sub-Window: {cw}x{ch} at ({cx}, {cy}) ({cw*ch*4 / 1024 / 1024:.1f} MB)")
    print(f"Data Reduction: {(1.0 - (cw*ch) / (3840*2160)) * 100:.1f}%")

if __name__ == "__main__":
    test_subwindow()
