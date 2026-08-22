import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time
from datetime import datetime, timedelta
import numpy as np

from src.indicators.time_display import render_time_display
from scratch.test_opt_time_display import optimized_render_time_display
from src.indicators.helpers import _STATIC_CACHE

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720
font_path = ""

# 1. Benchmark original across 120 frames
_STATIC_CACHE.clear()
orig_times = []
for i in range(120):
    t_sec = float(i) / 60.0
    cur_dt = datetime(2026, 8, 14, 11, 18, 10) + timedelta(seconds=t_sec)
    date_str = cur_dt.strftime("%Y.%m.%d")
    time_str = cur_dt.strftime("%H:%M:%S")
    avg_spd = 25.4 + (i % 3) * 0.1
    
    t0 = time.perf_counter()
    render_time_display(canvas_w, canvas_h, layout, font_path, date_str, time_str, t_sec, avg_spd)
    t1 = time.perf_counter()
    orig_times.append((t1 - t0) * 1000.0)

# 2. Benchmark optimized across 120 frames
_STATIC_CACHE.clear()
opt_times = []
for i in range(120):
    t_sec = float(i) / 60.0
    cur_dt = datetime(2026, 8, 14, 11, 18, 10) + timedelta(seconds=t_sec)
    date_str = cur_dt.strftime("%Y.%m.%d")
    time_str = cur_dt.strftime("%H:%M:%S")
    avg_spd = 25.4 + (i % 3) * 0.1
    
    t0 = time.perf_counter()
    optimized_render_time_display(canvas_w, canvas_h, layout, font_path, date_str, time_str, t_sec, avg_spd)
    t1 = time.perf_counter()
    opt_times.append((t1 - t0) * 1000.0)

print(f"Original Time Display (120 frames):  avg = {sum(orig_times)/len(orig_times):.3f} ms (median = {sorted(orig_times)[60]:.3f} ms, p95 = {sorted(orig_times)[114]:.3f} ms)")
print(f"Optimized Time Display (120 frames): avg = {sum(opt_times)/len(opt_times):.3f} ms (median = {sorted(opt_times)[60]:.3f} ms, p95 = {sorted(opt_times)[114]:.3f} ms)")
print(f"Speedup: {sum(orig_times)/sum(opt_times):.2f}x faster")
