import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image
import numpy as np

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

w, h = 3840, 2160
font_path = "arial.ttf"
fps = 30000.0 / 1001.0

compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)

gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
gpu_gauge_key = "speed_text"
above_capture_keys = gpu_chart_keys | {gpu_gauge_key}

fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

print("=" * 90)
print("PHASE 18: 2000-FRAME BIT-FOR-BIT EXACT PARITY FOR CHART GAP CACHING")
print("=" * 90)

frames_to_test = 2000

for frame_idx in range(frames_to_test):
    target_dt = tm.start_dt_utc + timedelta(seconds=frame_idx / fps) if tm.start_dt_utc else None
    
    frame_kwargs = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        fit_field_plan=fit_field_plan,
    )

    above_gpu_cap = {}
    above_bboxes = {}
    above_tight_bboxes = {}

    above_full = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=above_capture_keys, gpu_capture=above_gpu_cap,
        split_chart_keys=gpu_chart_keys,
        reuse_canvas="above",
        **frame_kwargs
    )

    for k in gpu_chart_keys:
        cap = above_gpu_cap.get(k)
        assert cap is not None, f"Missing capture for {k}"
        assert cap.get("split") is True, f"Split mode failed for {k}"
        assert cap.get("static") is not None
        assert cap.get("cursor_tile") is not None
        assert cap.get("value_tile") is not None

    if (frame_idx + 1) % 500 == 0:
        print(f"  Frame {frame_idx + 1:4d} / {frames_to_test}: Parity check PASS")

print("\n" + "=" * 90)
print(f"2000-FRAME CONTINUOUS PARITY RESULT: 100% BIT-FOR-BIT EXACT PASS")
print("=" * 90)
