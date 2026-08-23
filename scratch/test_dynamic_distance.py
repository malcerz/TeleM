import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np

from scratch.test_opt_distance import optimized_render_ruler
from src.indicators.helpers import _STATIC_CACHE, resolve_indicator_font_path, s

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720
min_dim = min(canvas_w, canvas_h)
outline = max(0, int(round(int(layout["global"].get("text_outline", 3)) * min_dim / 1000)))

dist_cfg = layout["indicators"]["dist_visual"]
size_px = s(dist_cfg.get("size", 10.0), canvas_w)
fs = max(10, s(dist_cfg.get("font_size", 1.0), min_dim))
unit = dist_cfg.get("unit", "km")
label = dist_cfg.get("label", "")
val_min = dist_cfg.get("min_val", 0.0)
val_max = dist_cfg.get("max_val", 10.0)

seq = [1.2, 5.0, 9.8, 0.5, None]
prev_arr = None

print("--- Testing Dynamic Distance Sequence ---")
for val in seq:
    fv = f"{val:.1f} km" if val is not None else "--"
    img = optimized_render_ruler(
        canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
        value=val, unit=unit, label=label, cfg=dist_cfg,
        val_min=val_min, val_max=val_max,
        ticks=5, thickness=1, size_px=size_px, fs=fs,
        outline=outline, ss=1, formatted_val=fv,
    )
    arr = np.array(img)
    if prev_arr is not None:
        if arr.shape != prev_arr.shape:
            print(f"Step to val={str(val):5}: shape changed from {prev_arr.shape} to {arr.shape} (Distinct: True)")
        else:
            diff = np.abs(arr.astype(np.int16) - prev_arr.astype(np.int16)).max()
            print(f"Step to val={str(val):5}: max diff from prev = {diff} (Distinct: {diff > 0})")
            assert diff > 0, f"Expected distinct image for step to {val}, got identical"
    prev_arr = arr

print("\nALL DYNAMIC DISTANCE TESTS PASSED!")
