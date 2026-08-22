import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np
from PIL import Image

from src.indicators.time_display import render_time_display
from scratch.test_opt_time_display import optimized_render_time_display
from src.indicators.helpers import _STATIC_CACHE

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720

_STATIC_CACHE.clear()
orig_img, orig_x, orig_y = render_time_display(
    canvas_w, canvas_h, layout, "",
    "2026.08.14", "11:19:03", 60.0, 25.4
)

_STATIC_CACHE.clear()
opt_img, opt_x, opt_y = optimized_render_time_display(
    canvas_w, canvas_h, layout, "",
    "2026.08.14", "11:19:03", 60.0, 25.4
)

orig_img.save("scratch/td_orig.png")
opt_img.save("scratch/td_opt.png")

orig_arr = np.array(orig_img)
opt_arr = np.array(opt_img)

print(f"orig shape: {orig_arr.shape}, opt shape: {opt_arr.shape}")
diff = np.abs(orig_arr.astype(np.int16) - opt_arr.astype(np.int16))
y_diff, x_diff, c_diff = np.where(diff > 0)
print(f"Total differing pixel coordinates: {len(y_diff)}")
if len(y_diff) > 0:
    print(f"Sample differing coords: y in [{y_diff.min()}..{y_diff.max()}], x in [{x_diff.min()}..{x_diff.max()}]")
    for idx in range(min(5, len(y_diff))):
        y, x, c = y_diff[idx], x_diff[idx], c_diff[idx]
        print(f"  at (y={y}, x={x}): orig={orig_arr[y, x]} vs opt={opt_arr[y, x]}")
