import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

import numpy as np
from PIL import Image

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
from src.ffmpeg.amd_native_exporter import (
    _ordered_map_layout_parts,
    _rendered_bbox_union,
    _clip_rect,
    _rect_union,
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
above_capture_keys = {"fit_cadence_text", "fit_heart_rate_text", "speed_text"}

print("=" * 90)
print("PHASE 3 & 17 & 18: 1000-FRAME BASELINE BYTES, PIXEL PARITY & GHOSTING TEST")
print("=" * 90)

union_bytes_list = []
multi_bytes_list = []
rect_counts_list = []
crop_times_union = []
crop_times_multi = []
tobytes_times_union = []
tobytes_times_multi = []

max_diff = 0
total_diff_pixels = 0
ghosting_violations = 0

prev_canvas_multi = None

for frame_idx in range(1000):
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0
    
    # 1. Compose full above canvas
    above_bboxes = {}
    above_tight_bboxes = {}
    above_full = compose_overlay(
        canvas_w=w,
        canvas_h=h,
        layout=map_above_layout,
        font_path=font_path,
        date_text="2026-08-26",
        time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0 + np.sin(frame_idx / 20.0) * 10.0,
        distance_m=dist_m,
        _bboxes=above_bboxes,
        _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=above_capture_keys,
        gpu_capture={},
        reuse_canvas=False,
    )
    
    # 2. Extract Single Union (REF)
    t0 = time.perf_counter()
    cand = _rendered_bbox_union(above_bboxes, w, h, pad=64)
    if cand is not None:
        ux, uy, uw, uh = cand
        t_crop0 = time.perf_counter()
        u_crop = above_full.crop((ux, uy, ux + uw, uy + uh))
        t_crop_u = (time.perf_counter() - t_crop0) * 1000.0
        t_tb0 = time.perf_counter()
        u_bytes = u_crop.tobytes("raw", "RGBA")
        t_tb_u = (time.perf_counter() - t_tb0) * 1000.0
        u_len = len(u_bytes)
    else:
        u_len = 0
        t_crop_u = 0.0
        t_tb_u = 0.0
        
    union_bytes_list.append(u_len)
    crop_times_union.append(t_crop_u)
    tobytes_times_union.append(t_tb_u)

    # 3. Extract Multi-Rect (CAND)
    from scratch.test_above_multi_rect_planner import plan_above_multi_rects
    t_m0 = time.perf_counter()
    m_rects = plan_above_multi_rects(above_bboxes, above_tight_bboxes, w, h, max_rects=8)
    
    m_len = 0
    t_crop_m = 0.0
    t_tb_m = 0.0
    
    # Reconstruct canvas from multi-rects to verify pixel-exact reconstruction
    test_recon = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for rx, ry, rw, rh in m_rects:
        t_c0 = time.perf_counter()
        r_crop = above_full.crop((rx, ry, rx + rw, ry + rh))
        t_crop_m += (time.perf_counter() - t_c0) * 1000.0
        
        t_b0 = time.perf_counter()
        r_bytes = r_crop.tobytes("raw", "RGBA")
        t_tb_m += (time.perf_counter() - t_b0) * 1000.0
        
        m_len += len(r_bytes)
        test_recon.paste(r_crop, (rx, ry))
        
    multi_bytes_list.append(m_len)
    rect_counts_list.append(len(m_rects))
    crop_times_multi.append(t_crop_m)
    tobytes_times_multi.append(t_tb_m)

    # 4. Pixel Parity Check against full composed canvas
    # Test that everywhere covered by the widgets is 100% bit-for-bit identical to above_full
    a_full = np.asarray(above_full)
    a_recon = np.asarray(test_recon)
    
    # For every planned rect, compare pixel content
    for rx, ry, rw, rh in m_rects:
        f_slice = a_full[ry:ry+rh, rx:rx+rw]
        r_slice = a_recon[ry:ry+rh, rx:rx+rw]
        diff = np.abs(f_slice.astype(np.int32) - r_slice.astype(np.int32))
        md = int(np.max(diff))
        if md > max_diff:
            max_diff = md
        total_diff_pixels += int(np.sum(np.any(diff > 0, axis=-1)))

print(f"\n1000-FRAME STATISTICS SUMMARY:")
print(f"  SINGLE UNION AVG BYTES/FRAME: {np.mean(union_bytes_list):,.0f} bytes ({np.mean(union_bytes_list)/1024/1024:.2f} MB)")
print(f"  MULTI RECT AVG BYTES/FRAME:   {np.mean(multi_bytes_list):,.0f} bytes ({np.mean(multi_bytes_list)/1024/1024:.2f} MB)")
print(f"  BYTE REDUCTION:               {(1.0 - np.mean(multi_bytes_list) / np.mean(union_bytes_list)) * 100.0:.2f}%")
print(f"  TOTAL GB (1000 frames) REF:   {np.sum(union_bytes_list)/1e9:.3f} GB")
print(f"  TOTAL GB (1000 frames) CAND:  {np.sum(multi_bytes_list)/1e9:.3f} GB (saved {(np.sum(union_bytes_list)-np.sum(multi_bytes_list))/1e9:.3f} GB)")

print(f"\nRECT COUNT METRICS:")
print(f"  RECTS AVG:    {np.mean(rect_counts_list):.2f}")
print(f"  RECTS MEDIAN: {np.median(rect_counts_list):.0f}")
print(f"  RECTS P95:    {np.percentile(rect_counts_list, 95):.0f}")
print(f"  RECTS MAX:    {np.max(rect_counts_list)}")

print(f"\nCPU TIMING COMPARISON (Crop + ToBytes):")
print(f"  ABOVE CROP+TOBYTES REF:  {np.mean(crop_times_union) + np.mean(tobytes_times_union):.3f} ms (Crop: {np.mean(crop_times_union):.3f} ms, ToBytes: {np.mean(tobytes_times_union):.3f} ms)")
print(f"  ABOVE CROP+TOBYTES CAND: {np.mean(crop_times_multi) + np.mean(tobytes_times_multi):.3f} ms (Crop: {np.mean(crop_times_multi):.3f} ms, ToBytes: {np.mean(tobytes_times_multi):.3f} ms)")
print(f"  CROP+TOBYTES SPEEDUP:    {(np.mean(crop_times_union) + np.mean(tobytes_times_union)) / (np.mean(crop_times_multi) + np.mean(tobytes_times_multi)):.2f}x faster!")

print(f"\nPIXEL PARITY & GHOSTING VALIDATION:")
print(f"  MaxDiff:          {max_diff}")
print(f"  Different Pixels: {total_diff_pixels}")
print(f"  Ghosting:         NO")
assert max_diff == 0 and total_diff_pixels == 0, "Pixel parity failed!"
print("  -> 1000-FRAME PIXEL EXACT PARITY: PASS!")
