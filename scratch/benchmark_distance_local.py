import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time
from datetime import datetime, timedelta
import numpy as np
from PIL import Image

from src.indicators.dispatcher import render_value_indicator
from src.indicators.compositor import rotated_paste
from src.indicators.helpers import _STATIC_CACHE

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720
font_path = ""
dist_cfg = layout["indicators"]["dist_visual"]

# Warm-up (10 frames)
for i in range(10):
    val = 2.45 + (i % 5) * 0.05
    render_value_indicator(
        canvas_w, canvas_h, layout, font_path, "dist_visual", val, "km",
        dist_cfg.get("label", ""), cfg_override=dist_cfg, formatted_val=f"{val:.1f} km", supersample=1
    )

# Measure 120 frames
render_times = []
placement_times = []
total_times = []

canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

for i in range(120):
    val = 2.45 + (i % 5) * 0.05
    fv = f"{val:.1f} km"
    
    t0 = time.perf_counter()
    img, x, y, _ = render_value_indicator(
        canvas_w, canvas_h, layout, font_path, "dist_visual", val, "km",
        dist_cfg.get("label", ""), cfg_override=dist_cfg, formatted_val=fv, supersample=1
    )
    t1 = time.perf_counter()
    
    cx = x
    cy = y
    rotated_paste(canvas, img, cx, cy, 0, cache_key="dist_visual")
    t2 = time.perf_counter()
    
    r_ms = (t1 - t0) * 1000.0
    p_ms = (t2 - t1) * 1000.0
    render_times.append(r_ms)
    placement_times.append(p_ms)
    total_times.append(r_ms + p_ms)

print(f"Distance (120 frames):  renderer = {sum(render_times)/len(render_times):.3f} ms (median = {sorted(render_times)[60]:.3f} ms, p95 = {sorted(render_times)[114]:.3f} ms)")
print(f"Distance (120 frames):  placement = {sum(placement_times)/len(placement_times):.3f} ms (median = {sorted(placement_times)[60]:.3f} ms)")
print(f"Distance TOTAL:         avg = {sum(total_times)/len(total_times):.3f} ms (median = {sorted(total_times)[60]:.3f} ms, p95 = {sorted(total_times)[114]:.3f} ms)")
