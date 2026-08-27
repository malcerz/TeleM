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
    _draw_text_bounded,
    _get_ruler_text_metrics,
)

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]
alt_cfg = layout["indicators"]["alt_text"]

w, h = 3840, 2160
font_path = "arial.ttf"

print("=" * 80)
print("COMPREHENSIVE PARITY TEST: Bar Indicators (Horizontal & Vertical)")
print("=" * 80)

# Test 100 random values for horizontal ruler
max_diff_h = 0
total_diff_px_h = 0

for i in range(100):
    val = i * 0.453
    fv = f"{val:.1f} km"
    res_orig = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="fit_distance_text", value=val, unit="km", label="Dystans",
        cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
        ss=1, formatted_val=fv
    )[0]

    # Test candidate with direct _draw_text_bounded
    # Let's verify if _draw_text_bounded matches _draw_text_bounded_cached
    a_orig = np.asarray(res_orig)
    
    # Render with candidate logic
    res_cand = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km", label="Dystans",
        cfg=dist_cfg, val_min=0, val_max=100, ticks=0, thickness=3,
        size_px=int(60.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=fv
    )
    a_cand = np.asarray(res_cand)

    diff = np.abs(a_orig.astype(np.int32) - a_cand.astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_h:
        max_diff_h = md
    total_diff_px_h += int(np.sum(np.any(diff > 0, axis=-1)))

print(f"Horizontal Ruler (100 values): MaxDiff={max_diff_h}, Total Different Pixels={total_diff_px_h}")
if max_diff_h == 0:
    print("  -> HORIZONTAL RULER: 100% BIT-FOR-BIT PARITY PASSED!")

# Test 100 random values for vertical ruler (alt_text)
max_diff_v = 0
total_diff_px_v = 0

for i in range(100):
    val = 100.0 + i * 2.37
    fv = f"{val:.0f} m"
    res_orig = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="alt_text", value=val, unit="m", label="Alt",
        cfg=alt_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=500, ticks=0, thickness=3, size_px=int(1.0 * 2160 / 100.0),
        ss=1, formatted_val=fv
    )[0]

    res_cand = _render_ruler_vertical(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="m", label="Alt",
        cfg=alt_cfg, val_min=0, val_max=500, ticks=0, thickness=3,
        size_px=int(1.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=fv
    )
    a_orig = np.asarray(res_orig)
    a_cand = np.asarray(res_cand)

    diff = np.abs(a_orig.astype(np.int32) - a_cand.astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_v:
        max_diff_v = md
    total_diff_px_v += int(np.sum(np.any(diff > 0, axis=-1)))

print(f"Vertical Ruler (100 values): MaxDiff={max_diff_v}, Total Different Pixels={total_diff_px_v}")
if max_diff_v == 0:
    print("  -> VERTICAL RULER: 100% BIT-FOR-BIT PARITY PASSED!")
