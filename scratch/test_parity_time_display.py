import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np
from datetime import datetime, timedelta

from src.indicators.time_display import render_time_display as orig_render_time_display
from scratch.test_opt_time_display import render_time_display as opt_render_time_display
from src.indicators.helpers import _STATIC_CACHE, resolve_indicator_font_path

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720

test_cases = [
    {"desc": "t=60s standard", "s": 60.0, "font": "", "date": "2026.08.14", "time": "11:19:03", "spd": 25.4},
    {"desc": "t=180s standard", "s": 180.0, "font": "", "date": "2026.08.14", "time": "11:21:03", "spd": 32.1},
    {"desc": "t=300s standard", "s": 300.0, "font": "", "date": "2026.08.14", "time": "11:23:03", "spd": 19.8},
    {"desc": "Comic Sans font", "s": 75.0, "font": "Comic Sans", "date": "2026.08.14", "time": "11:19:18", "spd": 28.0},
    {"desc": "Digital-7 font", "s": 120.0, "font": "Digital-7", "date": "2026.08.14", "time": "11:20:03", "spd": 30.5},
    {"desc": "Iona-u1 font", "s": 240.0, "font": "Iona-u1", "date": "2026.08.14", "time": "11:22:03", "spd": 15.2},
    {"desc": "Long duration >1h", "s": 3725.0, "font": "", "date": "2026.08.14", "time": "12:20:08", "spd": 27.3},
]

print("=== PIXEL PARITY VERIFICATION ===")
for tc in test_cases:
    fpath = resolve_indicator_font_path(tc["font"], "")
    
    # 1. Render with original (after clearing cache)
    _STATIC_CACHE.clear()
    orig_img, orig_x, orig_y = orig_render_time_display(
        canvas_w, canvas_h, layout, fpath,
        tc["date"], tc["time"], tc["s"], tc["spd"]
    )
    
    # 2. Render with optimized (after clearing cache)
    _STATIC_CACHE.clear()
    opt_img, opt_x, opt_y = opt_render_time_display(
        canvas_w, canvas_h, layout, fpath,
        tc["date"], tc["time"], tc["s"], tc["spd"]
    )

    assert orig_x == opt_x and orig_y == opt_y, f"Placement mismatch for {tc['desc']}: ({orig_x},{orig_y}) vs ({opt_x},{opt_y})"
    
    orig_arr = np.array(orig_img)
    opt_arr = np.array(opt_img)

    assert orig_arr.shape == opt_arr.shape, f"Shape mismatch for {tc['desc']}: {orig_arr.shape} vs {opt_arr.shape}"
    diff = np.abs(orig_arr.astype(np.int16) - opt_arr.astype(np.int16)).max()
    print(f"[{tc['desc']:20}] shape={orig_arr.shape} max pixel diff = {diff} (Byte-exact: {diff == 0})")
    assert diff == 0, f"Pixel mismatch for {tc['desc']}: max diff = {diff}"

print("\nALL PARITY TESTS PASSED! 100% BYTE-EXACT MATCH!")
