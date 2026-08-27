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

# Disable CPU lean indicator since AMD_LEAN_GPU=1 is active
if "indicators" in map_above_layout and "lean_indicator" in map_above_layout["indicators"]:
    map_above_layout["indicators"]["lean_indicator"]["enabled"] = False

gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
gpu_gauge_key = "speed_text"
above_capture_keys = gpu_chart_keys | {gpu_gauge_key}

print("=" * 90)
print("PHASE 20: 1000-FRAME BIT-FOR-BIT PARITY: SPARSE COMPOSITOR vs PRODUCTION REFERENCE")
print("=" * 90)

max_diff_global = 0
diff_pixels_global = 0

t_ref_total = 0.0
t_cand_total = 0.0

frames_to_test = 1000

for frame_idx in range(frames_to_test):
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0
    alt_m = 250.0 + (frame_idx * 0.2) % 500.0
    temp_c = 22.0 + (frame_idx // 100) % 5
    iso_val = 100 if frame_idx < 1000 else 200
    exp_val = 240.0 if frame_idx < 1000 else 480.0

    # ─────────────────────────────────────────────────────────────
    # 1. PRODUCTION REFERENCE: compose_overlay (4K canvas) + crop
    # ─────────────────────────────────────────────────────────────
    above_bboxes_ref = {}
    above_tight_bboxes_ref = {}
    t0 = time.perf_counter()
    gt_canvas = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        date_text="2026-08-26", time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0 + np.sin(frame_idx / 20.0) * 10.0, distance_m=dist_m,
        alt_value=alt_m, temp_value=temp_c, iso_value=iso_val, exposure_value=exp_val,
        _bboxes=above_bboxes_ref, _tight_bboxes=above_tight_bboxes_ref,
        gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
    )
    clusters_ref = _cluster_above_bboxes_members(above_bboxes_ref, w, h, pad=16, merge_dist=32, max_regions=8)
    regions_ref, _ = _extract_exact_above_regions(gt_canvas, clusters_ref, above_tight_bboxes_ref, w, h)
    t_ref_total += (time.perf_counter() - t0)

    # ─────────────────────────────────────────────────────────────
    # 2. CANDIDATE: SPARSE / REGION-LOCAL COMPOSITOR
    # ─────────────────────────────────────────────────────────────
    t1 = time.perf_counter()
    
    # Render individual active widgets directly
    dist_cfg = map_above_layout["indicators"]["fit_distance_text"]
    dist_res, dist_rx, dist_ry, _ = render_value_indicator(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        key="fit_distance_text", value=dist_m,
        unit=dist_cfg.get("unit", "km"), label=dist_cfg.get("title", ""),
    )
    
    alt_cfg = map_above_layout["indicators"]["alt_text"]
    alt_res, alt_rx, alt_ry, _ = render_value_indicator(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        key="alt_text", value=alt_m,
        unit=alt_cfg.get("unit", "m"), label=alt_cfg.get("title", ""),
    )
    
    text_widgets = [("iso_text", iso_val), ("exposure_text", exp_val), ("temp_text", temp_c)]
    rendered_texts = []
    for k, val in text_widgets:
        cfg = map_above_layout["indicators"][k]
        r_img, rx, ry, _ = render_value_indicator(
            canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
            key=k, value=val,
            unit=cfg.get("unit", ""), label=cfg.get("title", ""),
        )
        rendered_texts.append((k, r_img, rx, ry))

    # Sparse region 0: Distance ruler (isolated cluster)
    dist_bytes = dist_res.tobytes("raw", "RGBA")
    cand_region_dist = (dist_rx, dist_ry, dist_res.width, dist_res.height, dist_bytes)

    # Sparse region 1: Altitude ruler (isolated cluster)
    alt_bytes = alt_res.tobytes("raw", "RGBA")
    cand_region_alt = (alt_rx, alt_ry, alt_res.width, alt_res.height, alt_bytes)

    # Sparse region 2: Stacked text indicators cluster (iso, exp, temp)
    min_tx = min(rx for _, _, rx, _ in rendered_texts)
    min_ty = min(ry for _, _, _, ry in rendered_texts)
    max_tx = max(rx + r_img.width for _, r_img, rx, _ in rendered_texts)
    max_ty = max(ry + r_img.height for _, r_img, _, ry in rendered_texts)
    tw = max_tx - min_tx
    th = max_ty - min_ty
    
    text_cluster_img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    for _, r_img, rx, ry in rendered_texts:
        text_cluster_img.paste(r_img, (rx - min_tx, ry - min_ty))
    text_bytes = text_cluster_img.tobytes("raw", "RGBA")
    cand_region_text = (min_tx, min_ty, tw, th, text_bytes)

    regions_cand = [cand_region_dist, cand_region_alt, cand_region_text]
    t_cand_total += (time.perf_counter() - t1)

    # ─────────────────────────────────────────────────────────────
    # VERIFY PRE-ENCODE BIT-FOR-BIT PARITY
    # ─────────────────────────────────────────────────────────────
    # Composite candidate regions onto a blank test canvas and compare against ground truth
    test_canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for rx, ry, rw, rh, r_b in regions_cand:
        patch = Image.frombytes("RGBA", (rw, rh), r_b)
        test_canvas.paste(patch, (rx, ry))

    diff = np.abs(np.asarray(gt_canvas).astype(np.int32) - np.asarray(test_canvas).astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_global:
        max_diff_global = md
    dp = int(np.sum(diff > 0) // 4)
    diff_pixels_global += dp

    if (frame_idx + 1) % 250 == 0:
        print(f"  Frame {frame_idx + 1:4d} / {frames_to_test}: MaxDiff = {max_diff_global}, DiffPx = {diff_pixels_global}")

print("\n" + "=" * 90)
print(f"PARITY VERIFICATION RESULTS ({frames_to_test} FRAMES):")
print(f"  MaxDiff:         {max_diff_global}")
print(f"  DifferentPixels: {diff_pixels_global}")
print(f"  REF Total Time:  {t_ref_total*1000.0/frames_to_test:.3f} ms / frame")
print(f"  CAND Total Time: {t_cand_total*1000.0/frames_to_test:.3f} ms / frame")
print(f"  Time Saved:      {(t_ref_total - t_cand_total)*1000.0/frames_to_test:.3f} ms / frame ({(1.0 - t_cand_total/t_ref_total)*100.0:.1f}%)")
if max_diff_global == 0 and diff_pixels_global == 0:
    print("  RESULT: 100% BIT-FOR-BIT EXACT PARITY PASS!")
else:
    print("  RESULT: FAILED PARITY")
print("=" * 90)
