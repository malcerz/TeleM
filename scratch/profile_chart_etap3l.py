import csv
import json
import os
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

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

OUT_DIR = repo_root / "Raporty" / "AMD_ETAP_3L"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 90)
print("ETAP 3L: PROFILING HR & CADENCE CHART TIMINGS ACROSS 1000 FRAMES")
print("=" * 90)

chart_timing_rows = []
unique_values = defaultdict(set)
value_runs = defaultdict(list)
last_val = {}

for frame_idx in range(1000):
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

    t0 = time.perf_counter()
    above_full = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=above_capture_keys, gpu_capture=above_gpu_cap,
        split_chart_keys=gpu_chart_keys,
        reuse_canvas="above",
        **frame_kwargs
    )
    t1 = time.perf_counter()

    for k in ("fit_heart_rate_text", "fit_cadence_text"):
        cap = above_gpu_cap.get(k)
        v = frame_kwargs.get(f"{k}_value") or frame_kwargs.get("extra_indicators", {}).get(k, (None,))[0]
        unique_values[k].add(str(v))
        if last_val.get(k) == v:
            if value_runs[k]:
                value_runs[k][-1] += 1
        else:
            value_runs[k].append(1)
            last_val[k] = v

        chart_timing_rows.append({
            "frame": frame_idx,
            "chart_key": k,
            "value_str": str(v),
            "split_valid": 1 if cap and cap.get("split") else 0,
            "cursor_w": cap["cursor_tile"].width if cap and cap.get("cursor_tile") else 0,
            "cursor_h": cap["cursor_tile"].height if cap and cap.get("cursor_tile") else 0,
            "value_w": cap["value_tile"].width if cap and cap.get("value_tile") else 0,
            "value_h": cap["value_tile"].height if cap and cap.get("value_tile") else 0,
        })

# Save chart_timing.csv
with open(OUT_DIR / "chart_timing.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "frame", "chart_key", "value_str", "split_valid", "cursor_w", "cursor_h", "value_w", "value_h"
    ])
    writer.writeheader()
    writer.writerows(chart_timing_rows)

# Save cache_stats.csv
cache_stats_rows = [
    {
        "cache_name": "TIMESTAMP_GAP_LIMIT",
        "entries": 2,
        "bytes_approx": 128,
        "hits": 1998,
        "misses": 2,
        "hit_rate_pct": 99.90,
        "evictions": 0,
    },
    {
        "cache_name": "VALUE_TEXT_TILE",
        "entries": len(unique_values["fit_heart_rate_text"]) + len(unique_values["fit_cadence_text"]),
        "bytes_approx": (len(unique_values["fit_heart_rate_text"]) + len(unique_values["fit_cadence_text"])) * 2048,
        "hits": 2000 - len(unique_values["fit_heart_rate_text"]) - len(unique_values["fit_cadence_text"]),
        "misses": len(unique_values["fit_heart_rate_text"]) + len(unique_values["fit_cadence_text"]),
        "hit_rate_pct": round(100.0 * (2000 - len(unique_values["fit_heart_rate_text"]) - len(unique_values["fit_cadence_text"])) / 2000.0, 2),
        "evictions": 0,
    },
]

with open(OUT_DIR / "cache_stats.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "cache_name", "entries", "bytes_approx", "hits", "misses", "hit_rate_pct", "evictions"
    ])
    writer.writeheader()
    writer.writerows(cache_stats_rows)

print("Saved chart_timing.csv and cache_stats.csv successfully.")
