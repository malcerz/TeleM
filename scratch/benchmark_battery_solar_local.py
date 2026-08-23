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

bat_cfg = layout["indicators"]["fit_battery_pct_text"]
sol_cfg = layout["indicators"]["fit_solar_pct_text"]

# Warm-up (10 frames)
for i in range(10):
    render_value_indicator(1280, 720, layout, "", "fit_battery_pct_text", 89.0, "%", bat_cfg.get("label", ""), cfg_override=bat_cfg, formatted_val="89%", supersample=1)
    render_value_indicator(1280, 720, layout, "", "fit_solar_pct_text", 100.0, "%", sol_cfg.get("label", ""), cfg_override=sol_cfg, formatted_val="100%", supersample=1)

def run_bench(key, cfg, val_fn):
    r_times, p_times, tot_times = [], [], []
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    for i in range(120):
        val = val_fn(i)
        fv = f"{int(val)}%" if val is not None else "--"
        t0 = time.perf_counter()
        img, x, y, _ = render_value_indicator(
            canvas_w, canvas_h, layout, "", key, val, "%", cfg.get("label", ""),
            cfg_override=cfg, formatted_val=fv, supersample=1
        )
        t1 = time.perf_counter()
        cx = x
        cy = y
        rotated_paste(canvas, img, cx, cy, 0, cache_key=key)
        t2 = time.perf_counter()
        
        r_ms = (t1 - t0) * 1000.0
        p_ms = (t2 - t1) * 1000.0
        r_times.append(r_ms)
        p_times.append(p_ms)
        tot_times.append(r_ms + p_ms)
    return r_times, p_times, tot_times

bat_r, bat_p, bat_tot = run_bench("fit_battery_pct_text", bat_cfg, lambda i: 89.0 - (i % 2) * 1.0)
sol_r, sol_p, sol_tot = run_bench("fit_solar_pct_text", sol_cfg, lambda i: 100.0 if i < 60 else (i % 101))

print(f"Battery (120 frames):  renderer = {sum(bat_r)/len(bat_r):.3f} ms (median = {sorted(bat_r)[60]:.3f} ms), placement = {sum(bat_p)/len(bat_p):.3f} ms, TOTAL = {sum(bat_tot)/len(bat_tot):.3f} ms")
print(f"Solar   (120 frames):  renderer = {sum(sol_r)/len(sol_r):.3f} ms (median = {sorted(sol_r)[60]:.3f} ms), placement = {sum(sol_p)/len(sol_p):.3f} ms, TOTAL = {sum(sol_tot)/len(sol_tot):.3f} ms")
print(f"Battery + Solar TOTAL: avg = {(sum(bat_tot)+sum(sol_tot))/len(bat_tot):.3f} ms (median = {sorted(bat_tot)[60]+sorted(sol_tot)[60]:.3f} ms)")
