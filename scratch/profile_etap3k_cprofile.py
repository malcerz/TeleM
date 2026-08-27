import cProfile
import json
import os
import pstats
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image
import numpy as np

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
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
if "indicators" in map_above_layout and "lean_indicator" in map_above_layout["indicators"]:
    map_above_layout["indicators"]["lean_indicator"]["enabled"] = False

gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
gpu_gauge_key = "speed_text"
above_capture_keys = gpu_chart_keys | {gpu_gauge_key}

print("=" * 90)
print("PHASE 10: cProfile of 100 frames inside compose_overlay(map_above_layout)")
print("=" * 90)

pr = cProfile.Profile()

for frame_idx in range(100):
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0
    alt_m = 250.0 + (frame_idx * 0.2) % 500.0
    temp_c = 22.0 + (frame_idx // 100) % 5
    iso_val = 100
    exp_val = 240.0

    frame_kwargs = {
        "date_text": "2026-08-26",
        "time_text": f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        "speed_value": 25.0,
        "distance_m": dist_m,
        "alt_value": alt_m,
        "temp_value": temp_c,
        "iso_value": iso_val,
        "exposure_value": exp_val,
    }

    above_bboxes = {}
    above_tight_bboxes = {}

    pr.enable()
    above_full = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
        **frame_kwargs
    )
    pr.disable()

stats = pstats.Stats(pr)
stats.strip_dirs()
stats.sort_stats("cumtime")
print("\n--- TOP 35 CUMULATIVE FUNCTIONS ---")
stats.print_stats(35)

stats.sort_stats("tottime")
print("\n--- TOP 35 TOTAL TIME (SELF TIME) FUNCTIONS ---")
stats.print_stats(35)
