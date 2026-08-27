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
from src.indicators.compositor import compose_overlay, _get_reusable_canvas
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
print("PHASE 2: EXACT MICRO-ACCOUNTING OF CPU ABOVE COMPOSE (300 FRAMES, LEAN_GPU=1)")
print("=" * 90)

substages = {
    "1. canvas_get_and_clear": [],
    "2. widget_render_ruler_dist": [],
    "3. widget_paste_ruler_dist": [],
    "4. widget_render_ruler_alt": [],
    "5. widget_paste_ruler_alt": [],
    "6. widget_render_texts": [],
    "7. widget_paste_texts": [],
    "8. multi_rect_cluster_plan": [],
    "9. multi_rect_crop_patches": [],
    "10. multi_rect_tobytes": [],
    "TOTAL_ABOVE_PIPELINE": [],
}

for frame_idx in range(300):
    t_start = time.perf_counter()
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0
    alt_m = 250.0 + (frame_idx * 0.2) % 500.0
    temp_c = 22.0 + (frame_idx // 100) % 5
    iso_val = 100 if frame_idx < 1000 else 200
    exp_val = 240.0 if frame_idx < 1000 else 480.0

    above_bboxes = {}
    above_tight_bboxes = {}

    # Stage 1: Canvas get and regional clear
    t0 = time.perf_counter()
    img, prev_bboxes, canvas_state = _get_reusable_canvas(w, h, canvas_type="above")
    if prev_bboxes:
        pad = 40
        for bx, by, bw, bh in prev_bboxes.values():
            x1 = max(0, bx - pad)
            y1 = max(0, by - pad)
            x2 = min(w, bx + bw + pad)
            y2 = min(h, by + bh + pad)
            img.paste((0, 0, 0, 0), (x1, y1, x2, y2))
        prev_bboxes.clear()
        canvas_state["is_clean"] = True
    elif not canvas_state.get("is_clean", False):
        img.paste((0, 0, 0, 0), (0, 0, w, h))
        canvas_state["is_clean"] = True
    t1 = time.perf_counter()
    substages["1. canvas_get_and_clear"].append((t1 - t0) * 1000.0)

    # Stage 2 & 3: Distance ruler
    t2 = time.perf_counter()
    dist_cfg = map_above_layout["indicators"]["fit_distance_text"]
    dist_res, dist_rx, dist_ry, _ = render_value_indicator(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        key="fit_distance_text", value=dist_m,
        unit=dist_cfg.get("unit", "km"), label=dist_cfg.get("title", ""),
    )
    t3 = time.perf_counter()
    substages["2. widget_render_ruler_dist"].append((t3 - t2) * 1000.0)

    t4 = time.perf_counter()
    rotated_paste(img, dist_res, dist_rx + dist_res.width // 2, dist_ry + dist_res.height // 2, 0,
                  tight_bboxes=above_tight_bboxes, tight_key="fit_distance_text")
    above_bboxes["fit_distance_text"] = (dist_rx, dist_ry, dist_res.width, dist_res.height)
    t5 = time.perf_counter()
    substages["3. widget_paste_ruler_dist"].append((t5 - t4) * 1000.0)

    # Stage 4 & 5: Altitude ruler
    t6 = time.perf_counter()
    alt_cfg = map_above_layout["indicators"]["alt_text"]
    alt_res, alt_rx, alt_ry, _ = render_value_indicator(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        key="alt_text", value=alt_m,
        unit=alt_cfg.get("unit", "m"), label=alt_cfg.get("title", ""),
    )
    t7 = time.perf_counter()
    substages["4. widget_render_ruler_alt"].append((t7 - t6) * 1000.0)

    t8 = time.perf_counter()
    rotated_paste(img, alt_res, alt_rx + alt_res.width // 2, alt_ry + alt_res.height // 2, 0,
                  tight_bboxes=above_tight_bboxes, tight_key="alt_text")
    above_bboxes["alt_text"] = (alt_rx, alt_ry, alt_res.width, alt_res.height)
    t9 = time.perf_counter()
    substages["5. widget_paste_ruler_alt"].append((t9 - t8) * 1000.0)

    # Stage 6 & 7: Text indicators
    t10 = time.perf_counter()
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
    t11 = time.perf_counter()
    substages["6. widget_render_texts"].append((t11 - t10) * 1000.0)

    t12 = time.perf_counter()
    for k, r_img, rx, ry in rendered_texts:
        rotated_paste(img, r_img, rx + r_img.width // 2, ry + r_img.height // 2, 0,
                      tight_bboxes=above_tight_bboxes, tight_key=k)
        above_bboxes[k] = (rx, ry, r_img.width, r_img.height)
    t13 = time.perf_counter()
    substages["7. widget_paste_texts"].append((t13 - t12) * 1000.0)

    # Stage 8: Multi-rect clustering
    t14 = time.perf_counter()
    clusters = _cluster_above_bboxes_members(above_bboxes, w, h, pad=16, merge_dist=32, max_regions=8)
    t15 = time.perf_counter()
    substages["8. multi_rect_cluster_plan"].append((t15 - t14) * 1000.0)

    # Stage 9 & 10: Multi-rect crop & tobytes
    regions_out, stats_p = _extract_exact_above_regions(img, clusters, above_tight_bboxes, w, h)
    substages["9. multi_rect_crop_patches"].append(stats_p.get("exact_crop_ms", 0.0))
    substages["10. multi_rect_tobytes"].append(stats_p.get("tobytes_ms", 0.0))

    t_end = time.perf_counter()
    substages["TOTAL_ABOVE_PIPELINE"].append((t_end - t_start) * 1000.0)

print(f"{'Substage':<35} {'AVG (ms)':<12} {'Median (ms)':<12} {'P95 (ms)':<12} {'Share (%)':<10}")
print("-" * 80)
total_avg = np.mean(substages["TOTAL_ABOVE_PIPELINE"])
accounted_sum = 0.0

for k, v in substages.items():
    if k != "TOTAL_ABOVE_PIPELINE":
        avg_k = np.mean(v)
        accounted_sum += avg_k
        share_k = (avg_k / total_avg) * 100.0 if total_avg > 0 else 0.0
        print(f"{k:<35} {avg_k:<12.3f} {np.median(v):<12.3f} {np.percentile(v, 95):<12.3f} {share_k:<10.1f}%")

print("-" * 80)
print(f"{'TOTAL ACCOUNTED SUM':<35} {accounted_sum:<12.3f} {'-':<12} {'-':<12} {accounted_sum/total_avg*100.0:<10.1f}%")
print(f"{'MEASURED TOTAL ABOVE PIPELINE':<35} {total_avg:<12.3f} {np.median(substages['TOTAL_ABOVE_PIPELINE']):<12.3f} {np.percentile(substages['TOTAL_ABOVE_PIPELINE'], 95):<12.3f} 100.0%")
print("=" * 90)
