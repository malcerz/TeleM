import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.bar import (
    _render_bar_indicator,
    _render_ruler,
    _render_ruler_vertical,
    _resolve_major_tick_plan,
)

VIDEO = Path("Video/GX030120.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
layout = json.load(open("def_layout.json", encoding="utf-8"))

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

dist_cfg = layout["indicators"]["fit_distance_text"]
alt_cfg = layout["indicators"]["alt_text"]

print("=" * 90)
print("PHASE 2: REAL 2001F VARIABILITY ANALYSIS (GX030120 + def_layout)")
print("=" * 90)

# 1. Horizontal: fit_distance_text
dist_values = []
dist_tick_plans = []
dist_marker_positions = []

for i in range(2001):
    t_sec = i / fps
    # sample distance from fit
    d_samp = tm.track_samples
    idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    val_m = d_samp[idx][1] if d_samp else 0.0
    val_km = val_m / 1000.0
    dist_values.append(val_km)
    
    plan = _resolve_major_tick_plan(dist_cfg, 0.0, 100.0, 0)
    dist_tick_plans.append(plan)
    
    frac = val_km / 100.0
    marker_x = int(round(32 + frac * 1296))
    dist_marker_positions.append(marker_x)

print(f"fit_distance_text (Horizontal Ruler):")
print(f"  Frames:                      2001")
print(f"  Unique Values:               {len(set(dist_values))}")
print(f"  Unique Tick Plans:           {len(set(dist_tick_plans))} (Mode/Step/Divisions/Minor = {dist_tick_plans[0]})")
print(f"  Scale Origin/Ticks Static?   {'YES (100% STATIC)' if len(set(dist_tick_plans)) == 1 else 'NO'}")
print(f"  Unique Marker Positions:     {len(set(dist_marker_positions))} distinct X positions")

# 2. Vertical: alt_text
alt_values = []
alt_tick_plans = []
alt_marker_positions = []

for i in range(2001):
    t_sec = i / fps
    a_samp = tm.alt_samples
    idx = min(len(a_samp) - 1, int(t_sec * 10)) if a_samp else 0
    val_alt = a_samp[idx][1] if (a_samp and len(a_samp[idx]) >= 2) else (a_samp[idx][0] if a_samp else 0.0)
    alt_values.append(val_alt)
    
    plan = _resolve_major_tick_plan(alt_cfg, 0.0, 500.0, 0)
    alt_tick_plans.append(plan)
    
    frac = (val_alt - 0.0) / 500.0
    marker_y = int(round(200 - frac * 200))
    alt_marker_positions.append(marker_y)

print(f"\nalt_text (Vertical Ruler):")
print(f"  Frames:                      2001")
print(f"  Unique Values:               {len(set(alt_values))}")
print(f"  Unique Tick Plans:           {len(set(alt_tick_plans))} (Mode/Step/Divisions/Minor = {alt_tick_plans[0]})")
print(f"  Scale Origin/Ticks Static?   {'YES (100% STATIC)' if len(set(alt_tick_plans)) == 1 else 'NO'}")
print(f"  Unique Marker Positions:     {len(set(alt_marker_positions))} distinct Y positions")

print("\n" + "=" * 90)
print("PHASE 4: PIXEL CHANGE ANALYSIS (Frame N vs N-1 across 300 frames)")
print("=" * 90)

# Measure changed pixel bbox for fit_distance_text and alt_text
prev_dist_img = None
dist_diff_areas = []
dist_changed_pixels = []

for i in range(300):
    val = dist_values[i]
    img = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="fit_distance_text", value=val, unit="km", label="Dystans",
        cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
        ss=1, formatted_val=f"{val:.1f} km"
    )[0]
    if prev_dist_img is not None:
        a1 = np.asarray(prev_dist_img)
        a2 = np.asarray(img)
        diff = np.any(a1 != a2, axis=-1)
        ch_px = int(np.sum(diff))
        dist_changed_pixels.append(ch_px)
        if ch_px > 0:
            ys, xs = np.where(diff)
            bx = int(np.min(xs)), int(np.min(ys)), int(np.max(xs) - np.min(xs) + 1), int(np.max(ys) - np.min(ys) + 1)
            dist_diff_areas.append(bx[2] * bx[3])
    prev_dist_img = img

full_area_dist = prev_dist_img.width * prev_dist_img.height
print(f"fit_distance_text (Horizontal 1316x125 = {full_area_dist} px):")
print(f"  Avg Changed Pixels / frame:  {np.mean(dist_changed_pixels):.1f} px ({np.mean(dist_changed_pixels)/full_area_dist*100.0:.2f}%)")
print(f"  Avg Changed Bbox Area:       {np.mean(dist_diff_areas):.1f} px ({np.mean(dist_diff_areas)/full_area_dist*100.0:.2f}%)")
print(f"  STATIC AREA OF WIDGET:       {100.0 - np.mean(dist_changed_pixels)/full_area_dist*100.0:.2f}% of pixels DO NOT CHANGE!")

# Measure for alt_text
prev_alt_img = None
alt_diff_areas = []
alt_changed_pixels = []

for i in range(300):
    val = alt_values[i]
    img = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="alt_text", value=val, unit="m", label="Alt",
        cfg=alt_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=500, ticks=0, thickness=3, size_px=int(1.0 * 2160 / 100.0),
        ss=1, formatted_val=f"{val:.0f} m"
    )[0]
    if prev_alt_img is not None:
        a1 = np.asarray(prev_alt_img)
        a2 = np.asarray(img)
        diff = np.any(a1 != a2, axis=-1)
        ch_px = int(np.sum(diff))
        alt_changed_pixels.append(ch_px)
        if ch_px > 0:
            ys, xs = np.where(diff)
            bx = int(np.min(xs)), int(np.min(ys)), int(np.max(xs) - np.min(xs) + 1), int(np.max(ys) - np.min(ys) + 1)
            alt_diff_areas.append(bx[2] * bx[3])
    prev_alt_img = img

full_area_alt = prev_alt_img.width * prev_alt_img.height
print(f"\nalt_text (Vertical 215x213 = {full_area_alt} px):")
print(f"  Avg Changed Pixels / frame:  {np.mean(alt_changed_pixels):.1f} px ({np.mean(alt_changed_pixels)/full_area_alt*100.0:.2f}%)")
print(f"  Avg Changed Bbox Area:       {np.mean(alt_diff_areas):.1f} px ({np.mean(alt_diff_areas)/full_area_alt*100.0:.2f}%)")
print(f"  STATIC AREA OF WIDGET:       {100.0 - np.mean(alt_changed_pixels)/full_area_alt*100.0:.2f}% of pixels DO NOT CHANGE!")
