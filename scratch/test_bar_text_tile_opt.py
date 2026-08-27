import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from src.indicators.bar import (
    _render_ruler,
    _render_ruler_vertical,
    _RULER_BASE_CACHE,
    _TEXT_TILE_CACHE,
    _draw_text_bounded,
    _draw_text_bounded_cached,
)
from src.indicators.helpers import load_font

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]
w, h = 3840, 2160
font_path = "arial.ttf"

print("=" * 90)
print("TESTING BAR TEXT TILE CACHE PERFORMANCE ACROSS 2001 REAL FRAMES")
print("=" * 90)

# Simulate 2001 real frames from GX030120
times_ref = []
for i in range(2001):
    val = (i / 2001.0) * 45.0
    fv = f"{val:.1f} km"
    t0 = time.perf_counter()
    img_ref = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km", label="Dystans",
        cfg=dist_cfg, val_min=0, val_max=100, ticks=0, thickness=3,
        size_px=int(60.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=fv
    )
    times_ref.append((time.perf_counter() - t0) * 1000.0)

print(f"Current _render_ruler (2001 calls):")
print(f"  Avg:    {np.mean(times_ref):.4f} ms")
print(f"  Median: {np.median(times_ref):.4f} ms")
print(f"  P95:    {np.percentile(times_ref, 95):.4f} ms")
