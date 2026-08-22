import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time
from datetime import datetime, timedelta
import numpy as np

from src.indicators.time_display import render_time_display
from src.indicators.compositor import rotated_paste
from src.indicators.helpers import _STATIC_CACHE
from PIL import Image

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720
font_path = ""

# Warm-up (10 frames)
for i in range(10):
    t_sec = float(i) / 60.0
    cur_dt = datetime(2026, 8, 14, 11, 18, 10) + timedelta(seconds=t_sec)
    render_time_display(canvas_w, canvas_h, layout, font_path, cur_dt.strftime("%Y.%m.%d"), cur_dt.strftime("%H:%M:%S"), t_sec, 25.4)

# Measure 120 frames
render_times = []
placement_times = []
total_times = []

canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

for i in range(120):
    t_sec = float(i) / 60.0
    cur_dt = datetime(2026, 8, 14, 11, 18, 10) + timedelta(seconds=t_sec)
    date_str = cur_dt.strftime("%Y.%m.%d")
    time_str = cur_dt.strftime("%H:%M:%S")
    avg_spd = 25.4 + (i % 3) * 0.1
    
    t0 = time.perf_counter()
    td, tdx, tdy = render_time_display(canvas_w, canvas_h, layout, font_path, date_str, time_str, t_sec, avg_spd)
    t1 = time.perf_counter()
    
    cx = tdx + td.width // 2
    cy = tdy + td.height // 2
    rotated_paste(canvas, td, cx, cy, 0, cache_key="time_display")
    t2 = time.perf_counter()
    
    r_ms = (t1 - t0) * 1000.0
    p_ms = (t2 - t1) * 1000.0
    render_times.append(r_ms)
    placement_times.append(p_ms)
    total_times.append(r_ms + p_ms)

print(f"Time Display Renderer:  avg = {sum(render_times)/len(render_times):.3f} ms (median = {sorted(render_times)[60]:.3f} ms, p95 = {sorted(render_times)[114]:.3f} ms)")
print(f"Time Display Placement: avg = {sum(placement_times)/len(placement_times):.3f} ms (median = {sorted(placement_times)[60]:.3f} ms)")
print(f"Time Display Total:     avg = {sum(total_times)/len(total_times):.3f} ms (median = {sorted(total_times)[60]:.3f} ms)")
