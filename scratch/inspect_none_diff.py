import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np
from PIL import Image

from src.indicators.bar import _render_segments
from scratch.test_opt_segment_bar import optimized_render_segments
from src.indicators.helpers import _STATIC_CACHE, resolve_indicator_font_path, s

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720
min_dim = min(canvas_w, canvas_h)
outline = max(0, int(round(int(layout["global"].get("text_outline", 3)) * min_dim / 1000)))

wkey = "fit_battery_pct_text"
cfg = layout["indicators"][wkey]
size_px = s(cfg.get("size", 10.0), canvas_w)
fs = max(10, s(cfg.get("font_size", 1.0), min_dim))
unit = cfg.get("unit", "%")
label = cfg.get("label", "")
val_min = cfg.get("min_val", 0.0)
val_max = cfg.get("max_val", 100.0)
fpath = resolve_indicator_font_path("Digital-7", "")

_STATIC_CACHE.clear()
orig_img = _render_segments(
    canvas_w=canvas_w, canvas_h=canvas_h, font_path=fpath,
    value=0.0, unit=unit, label=label, cfg=cfg,
    val_min=val_min, val_max=val_max,
    size_px=size_px, fs=fs, outline=outline,
    ss=1, formatted_val="--",
)

_STATIC_CACHE.clear()
opt_img = optimized_render_segments(
    canvas_w=canvas_w, canvas_h=canvas_h, font_path=fpath,
    value=None, unit=unit, label=label, cfg=cfg,
    val_min=val_min, val_max=val_max,
    size_px=size_px, fs=fs, outline=outline,
    ss=1, formatted_val="--",
)

orig_arr = np.array(orig_img)
opt_arr = np.array(opt_img)

print(f"orig shape: {orig_arr.shape}, opt shape: {opt_arr.shape}")
diff = np.abs(orig_arr.astype(np.int16) - opt_arr.astype(np.int16))
y_diff, x_diff, c_diff = np.where(diff > 0)
print(f"Total differing pixel coordinates: {len(y_diff)}")
if len(y_diff) > 0:
    for idx in range(min(5, len(y_diff))):
        y, x, c = y_diff[idx], x_diff[idx], c_diff[idx]
        print(f"  at (y={y}, x={x}): orig={orig_arr[y, x]} vs opt={opt_arr[y, x]}")
