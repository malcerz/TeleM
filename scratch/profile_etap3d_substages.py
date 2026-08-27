import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from src.indicators.bar import (
    _render_ruler,
    _render_ruler_vertical,
    _render_bar_indicator,
    _RULER_BASE_CACHE,
    _draw_text_bounded,
    _get_ruler_text_metrics,
    _fraction,
    _resolve_major_tick_plan,
    _static_cache_key,
    load_font,
    _line_with_shadow,
)

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]
alt_cfg = layout["indicators"]["alt_text"]

w, h = 3840, 2160
font_path = "arial.ttf"

print("=" * 90)
print("PHASE 3: SUBSTAGE PROFILING (2001 calls each for Horizontal & Vertical)")
print("=" * 90)

# Profile Horizontal Ruler (fit_distance_text)
h_timings = {
    "geometry": [],
    "tick_plan": [],
    "metrics_lookup": [],
    "cache_lookup": [],
    "base_copy": [],
    "marker_draw": [],
    "value_text_draw": [],
    "total": [],
}

_RULER_BASE_CACHE.clear()

for i in range(2001):
    val = (i / 2001.0) * 45.0
    fv = f"{val:.1f} km"
    
    t_tot0 = time.perf_counter()
    
    t0 = time.perf_counter()
    ss = 1
    width = max(80 * ss, int(int(60.0 * 2160 / 100.0) * ss))
    title_fs = max(8 * ss, int(round(float(dist_cfg.get("title_font_scale", 1.00)) * 24 * ss)))
    label_fs = max(7 * ss, int(round(float(dist_cfg.get("range_font_scale", 0.82)) * 24 * ss)))
    value_fs = max(8 * ss, int(round(float(dist_cfg.get("value_font_scale", 1.00)) * 24 * ss)))
    title_font = load_font(font_path, title_fs)
    range_font = load_font(font_path, label_fs)
    value_font = load_font(font_path, value_fs)
    text_stroke = max(0, int(round(max(1, 3) * ss)))
    t_geom = (time.perf_counter() - t0) * 1000.0
    h_timings["geometry"].append(t_geom)
    
    t0 = time.perf_counter()
    _mode, major_step, major_divisions, minor_per_major = _resolve_major_tick_plan(dist_cfg, 0, 100, 0)
    t_plan = (time.perf_counter() - t0) * 1000.0
    h_timings["tick_plan"].append(t_plan)
    
    t0 = time.perf_counter()
    title_h, range_h, value_h = _get_ruler_text_metrics(
        font_path, "DYSTANS", title_font, True,
        "100 km", range_font, True,
        fv, value_font, True, text_stroke,
    )
    t_met = (time.perf_counter() - t0) * 1000.0
    h_timings["metrics_lookup"].append(t_met)
    
    t0 = time.perf_counter()
    # Cache key
    pad_x = max(7 + 4 * ss, 8 * ss)
    pad_top = 4 * ss
    title_gap = 5 * ss if title_h else 0
    value_gap = 4 * ss if value_h else 0
    track_y = pad_top + title_h + title_gap + value_h + value_gap + 17 + 7
    bottom_gap = 6 * ss
    height = int(track_y + 7 + bottom_gap + range_h + 5 * ss)
    raster_w = width + pad_x * 2
    static_key = _static_cache_key(
        "bar_ruler_v3", raster_w, height, width, track_y, pad_x, pad_top,
        "DYSTANS", font_path, title_fs, label_fs, value_fs, text_stroke,
        True, True, True, True, True, 1, 0, 100, "km", major_divisions, minor_per_major, major_step,
        (244, 244, 244, 235), (246, 246, 246, 240), (244, 244, 244, 255), (224, 224, 224, 255),
        (21, 159, 165, 255), (216, 216, 216, 255), 7, 2, 1, 1, 17, 10, False, ss,
        title_h, title_gap, value_h, value_gap,
    )
    base_data = _RULER_BASE_CACHE.get(static_key)
    if base_data is None:
        base = Image.new("RGBA", (raster_w, height), (0, 0, 0, 0))
        base_data = (
            base, pad_x, width, track_y, 7, 2, (216, 216, 216, 255),
            (21, 159, 165, 255), True, title_h, title_gap, pad_top, value_font,
            (244, 244, 244, 255), text_stroke, raster_w, height, ss, 0, 100
        )
        _RULER_BASE_CACHE[static_key] = base_data
    t_cache = (time.perf_counter() - t0) * 1000.0
    h_timings["cache_lookup"].append(t_cache)
    
    t0 = time.perf_counter()
    img = base_data[0].copy()
    t_copy = (time.perf_counter() - t0) * 1000.0
    h_timings["base_copy"].append(t_copy)
    
    t0 = time.perf_counter()
    d = ImageDraw.Draw(img)
    frac = _fraction(val, 0, 100)
    marker_x = int(round(pad_x + frac * width))
    d.ellipse((marker_x - 9, track_y - 9, marker_x + 9, track_y + 9), fill=(0, 0, 0, 130))
    d.ellipse((marker_x - 9, track_y - 9, marker_x + 9, track_y + 9), fill=(216, 216, 216, 255))
    d.ellipse((marker_x - 7, track_y - 7, marker_x + 7, track_y + 7), fill=(21, 159, 165, 255))
    t_mark = (time.perf_counter() - t0) * 1000.0
    h_timings["marker_draw"].append(t_mark)
    
    t0 = time.perf_counter()
    value_y = pad_top + title_h + (title_gap if title_h else 0)
    _draw_text_bounded(
        d, (marker_x, value_y), fv,
        font=value_font, fill=(244, 244, 244, 255),
        stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
        bounds=(raster_w, height), anchor="ma",
    )
    t_val = (time.perf_counter() - t0) * 1000.0
    h_timings["value_text_draw"].append(t_val)
    
    t_tot = (time.perf_counter() - t_tot0) * 1000.0
    h_timings["total"].append(t_tot)

print(f"{'Horizontal Substage':<25} {'Mean (ms)':<12} {'Median (ms)':<12} {'P95 (ms)':<12}")
print("-" * 75)
for k, v in h_timings.items():
    print(f"{k:<25} {np.mean(v):<12.4f} {np.median(v):<12.4f} {np.percentile(v, 95):<12.4f}")

# Profile Vertical Ruler (alt_text)
v_timings = {
    "total": []
}
for i in range(2001):
    val = 100.0 + (i / 2001.0) * 350.0
    fv = f"{val:.0f} m"
    t0 = time.perf_counter()
    _render_ruler_vertical(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="m", label="Alt",
        cfg=alt_cfg, val_min=0, val_max=500, ticks=0, thickness=3,
        size_px=int(1.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=fv
    )
    v_timings["total"].append((time.perf_counter() - t0) * 1000.0)

print(f"\n{'Vertical Substage':<25} {'Mean (ms)':<12} {'Median (ms)':<12} {'P95 (ms)':<12}")
print("-" * 75)
print(f"{'total':<25} {np.mean(v_timings['total']):<12.4f} {np.median(v_timings['total']):<12.4f} {np.percentile(v_timings['total'], 95):<12.4f}")
