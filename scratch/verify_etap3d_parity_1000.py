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
)

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]
alt_cfg = layout["indicators"]["alt_text"]

w, h = 3840, 2160
font_path = "arial.ttf"

print("=" * 90)
print("PHASE 9: EXACT PIXEL PARITY TEST (500 Horizontal + 500 Vertical Values)")
print("=" * 90)

# 1. Horizontal (500 values)
max_diff_h = 0
total_diff_px_h = 0

for i in range(500):
    val = (i / 500.0) * 45.0
    fv = f"{val:.1f} km"
    
    img1 = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km", label="Dystans",
        cfg=dist_cfg, val_min=0, val_max=100, ticks=0, thickness=3,
        size_px=int(60.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=fv
    )
    img2 = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="fit_distance_text", value=val, unit="km", label="Dystans",
        cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
        ss=1, formatted_val=fv
    )[0]
    
    a1 = np.asarray(img1)
    a2 = np.asarray(img2)
    diff = np.abs(a1.astype(np.int32) - a2.astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_h:
        max_diff_h = md
    total_diff_px_h += int(np.sum(np.any(diff > 0, axis=-1)))

print(f"Horizontal Parity (500 values): MaxDiff={max_diff_h}, Total Different Pixels={total_diff_px_h}")
assert max_diff_h == 0 and total_diff_px_h == 0, "Horizontal parity failed!"
print("  -> HORIZONTAL RULER: 100% BIT-FOR-BIT EXACT PARITY PASS!")

# 2. Vertical (500 values)
max_diff_v = 0
total_diff_px_v = 0

for i in range(500):
    val = 100.0 + (i / 500.0) * 350.0
    fv = f"{val:.0f} m"
    
    img1 = _render_ruler_vertical(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="m", label="Alt",
        cfg=alt_cfg, val_min=0, val_max=500, ticks=0, thickness=3,
        size_px=int(1.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=fv
    )
    img2 = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="alt_text", value=val, unit="m", label="Alt",
        cfg=alt_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=500, ticks=0, thickness=3, size_px=int(1.0 * 2160 / 100.0),
        ss=1, formatted_val=fv
    )[0]
    
    a1 = np.asarray(img1)
    a2 = np.asarray(img2)
    diff = np.abs(a1.astype(np.int32) - a2.astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_v:
        max_diff_v = md
    total_diff_px_v += int(np.sum(np.any(diff > 0, axis=-1)))

print(f"Vertical Parity (500 values): MaxDiff={max_diff_v}, Total Different Pixels={total_diff_px_v}")
assert max_diff_v == 0 and total_diff_px_v == 0, "Vertical parity failed!"
print("  -> VERTICAL RULER: 100% BIT-FOR-BIT EXACT PARITY PASS!")
