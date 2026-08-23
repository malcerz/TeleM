import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np
from PIL import Image
from src.indicators.bar import _render_ruler, _RULER_BASE_CACHE

root = Path(__file__).resolve().parents[1]
layout_path = root / "presets" / "cycling_dashboard_v10.json"
with open(layout_path, "r", encoding="utf-8") as f:
    v10_layout = json.load(f)

cfg = v10_layout["indicators"]["dist_visual"]

def find_marker_x(img, color=(255, 212, 42)):
    arr = np.array(img)
    mask = (arr[:, :, 0] == color[0]) & (arr[:, :, 1] == color[1]) & (arr[:, :, 2] == color[2]) & (arr[:, :, 3] > 200)
    ys, xs = np.where(mask)
    if len(xs) > 0:
        return float(np.mean(xs)), int(np.min(xs)), int(np.max(xs))
    return None, None, None

print(f"Canvas size: 1280x720, cfg size: {cfg.get('size')}")

for val in [0.0, 1.0, 2.5, 5.0, 7.5, 10.0, None]:
    img = _render_ruler(
        canvas_w=1280, canvas_h=720, font_path="",
        value=val, unit="km", label="DISTANCE", cfg=cfg,
        val_min=0.0, val_max=10.0, ticks=5, thickness=1,
        size_px=int(0.28 * 1280), fs=15, outline=1, ss=1,
        formatted_val=f"{val:.1f} km" if val is not None else "-- km",
    )
    center_x, min_x, max_x = find_marker_x(img)
    # Also save sample image to scratch
    if val is not None:
        img.save(root / "scratch" / f"ruler_dist_{val:.1f}.png")
    else:
        img.save(root / "scratch" / "ruler_dist_none.png")
    print(f"val = {str(val):<5} | marker_center_x = {center_x} (min={min_x}, max={max_x}) | img size = {img.size}")
