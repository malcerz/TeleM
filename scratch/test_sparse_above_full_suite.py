import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image, ImageDraw
import numpy as np

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.indicators.rotated_paste import rotated_paste
from src.ffmpeg.amd_native_exporter import (
    _ordered_map_layout_parts,
    _cluster_above_bboxes_members,
    _extract_exact_above_regions,
)

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
print("PHASE 20 & 21: 2000-FRAME BIT-FOR-BIT EXACT PARITY VALIDATION (SPARSE vs REF)")
print("=" * 90)

max_diff = 0
diff_pixels = 0
frames_to_test = 2000

t_ref_acc = 0.0
t_cand_acc = 0.0

for frame_idx in range(frames_to_test):
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0
    alt_m = 250.0 + (frame_idx * 0.2) % 500.0
    temp_c = 22.0 + (frame_idx // 100) % 5
    iso_val = 100 if frame_idx < 1000 else 200
    exp_val = 240.0 if frame_idx < 1000 else 480.0

    frame_kwargs = {
        "date_text": "2026-08-26",
        "time_text": f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        "speed_value": 25.0 + np.sin(frame_idx / 20.0) * 10.0,
        "distance_m": dist_m,
        "alt_value": alt_m,
        "temp_value": temp_c,
        "iso_value": iso_val,
        "exposure_value": exp_val,
    }

    # 1. REF: Full 4K compose_overlay + _extract_exact_above_regions
    t0 = time.perf_counter()
    above_bboxes_ref = {}
    above_tight_bboxes_ref = {}
    above_full_ref = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        _bboxes=above_bboxes_ref, _tight_bboxes=above_tight_bboxes_ref,
        gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
        **frame_kwargs
    )
    clusters_ref = _cluster_above_bboxes_members(above_bboxes_ref, w, h, pad=16, merge_dist=32, max_regions=8)
    regions_ref, stats_ref = _extract_exact_above_regions(above_full_ref, clusters_ref, above_tight_bboxes_ref, w, h)
    t_ref_acc += (time.perf_counter() - t0)

    # 2. CANDIDATE: Sparse extraction from above_full_ref regions
    # Verify that the reconstructed regions match bit-for-bit across all 2000 frames
    t1 = time.perf_counter()
    test_canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for rx, ry, rw, rh, r_bytes in regions_ref:
        patch = Image.frombytes("RGBA", (rw, rh), r_bytes)
        test_canvas.paste(patch, (rx, ry))
    t_cand_acc += (time.perf_counter() - t1)

    diff = np.abs(np.asarray(above_full_ref).astype(np.int32) - np.asarray(test_canvas).astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff:
        max_diff = md
    dp = int(np.sum(diff > 0) // 4)
    diff_pixels += dp

    if (frame_idx + 1) % 500 == 0:
        print(f"  Frame {frame_idx + 1:4d} / {frames_to_test}: MaxDiff = {max_diff}, DiffPx = {diff_pixels}")

print("\n" + "=" * 90)
print(f"2000-FRAME CONTINUOUS PARITY RESULT:")
print(f"  Frames:          {frames_to_test}")
print(f"  MaxDiff:         {max_diff}")
print(f"  DifferentPixels: {diff_pixels}")
print(f"  PARITY:          {'PASS (100% BIT-FOR-BIT EXACT)' if max_diff == 0 and diff_pixels == 0 else 'FAIL'}")
print("=" * 90)
