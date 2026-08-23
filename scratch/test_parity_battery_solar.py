import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np

from src.indicators.bar import _render_segments
from scratch.test_opt_segment_bar import (
    optimized_render_segments, _SEG_BASE_CACHE, _SEG_ACTIVE_CACHE
)
from src.indicators.helpers import _STATIC_CACHE, resolve_indicator_font_path, s

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720
min_dim = min(canvas_w, canvas_h)
outline = max(0, int(round(int(layout["global"].get("text_outline", 3)) * min_dim / 1000)))

test_widgets = ["fit_battery_pct_text", "fit_solar_pct_text"]
test_values = [0.0, 5.0, 50.0, 89.0, 100.0, None]
test_fonts = ["", "Digital-7", "Iona-u1", "Comic Sans"]

print("=== PIXEL PARITY VERIFICATION (Battery & Solar) ===")

for wkey in test_widgets:
    cfg = layout["indicators"][wkey]
    size_px = s(cfg.get("size", 10.0), canvas_w)
    fs = max(10, s(cfg.get("font_size", 1.0), min_dim))
    unit = cfg.get("unit", "%")
    label = cfg.get("label", "")
    val_min = cfg.get("min_val", 0.0)
    val_max = cfg.get("max_val", 100.0)

    for font_name in test_fonts:
        fpath = resolve_indicator_font_path(font_name, "")
        for val in test_values:
            fv = f"{int(val)}%" if val is not None else "--"
            
            _STATIC_CACHE.clear()
            # Original call
            orig_img = _render_segments(
                canvas_w=canvas_w, canvas_h=canvas_h, font_path=fpath,
                value=val if val is not None else 0.0,
                unit=unit, label=label, cfg=cfg,
                val_min=val_min, val_max=val_max,
                size_px=size_px, fs=fs, outline=outline,
                ss=1, formatted_val=fv,
            )

            _STATIC_CACHE.clear()
            # Optimized call
            opt_img = optimized_render_segments(
                canvas_w=canvas_w, canvas_h=canvas_h, font_path=fpath,
                value=val, unit=unit, label=label, cfg=cfg,
                val_min=val_min, val_max=val_max,
                size_px=size_px, fs=fs, outline=outline,
                ss=1, formatted_val=fv,
            )

            orig_arr = np.array(orig_img)
            opt_arr = np.array(opt_img)

            assert orig_arr.shape == opt_arr.shape, f"Shape mismatch for {wkey} val={val} font='{font_name}': {orig_arr.shape} vs {opt_arr.shape}"
            diff = np.abs(orig_arr.astype(np.int16) - opt_arr.astype(np.int16)).max()
            tag = f"[{wkey[:12]}] font='{font_name or 'def':7}' val={str(val):5}"
            print(f"{tag:38} shape={orig_arr.shape} max pixel diff = {diff} (Byte-exact: {diff == 0})")
            assert diff == 0, f"Pixel mismatch for {wkey} val={val} font='{font_name}': max diff = {diff}"

print("\nALL PIXEL PARITY TESTS PASSED! 100% BYTE-EXACT MATCH!")
