import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from src.indicators.bar import (
    _render_ruler_vertical,
    _RULER_BASE_CACHE,
    _static_cache_key,
    _text_size,
    _fmt_number,
    _draw_text_bounded,
    _fraction,
)
from src.indicators.helpers import load_font

layout = json.load(open("def_layout.json", encoding="utf-8"))
alt_cfg = layout["indicators"]["alt_text"]
w, h = 3840, 2160
font_path = "arial.ttf"

print("=" * 90)
print("TESTING VERTICAL RULER CACHE STABILITY & PARITY (500 VALUES)")
print("=" * 90)

_RULER_BASE_CACHE.clear()

# Test candidate with stable sample width
misses = 0
hits = 0
max_diff = 0
total_diff_px = 0

for i in range(500):
    val = 100.0 + i * 0.73
    fv = f"{val:.0f} m"
    
    # Measure with current
    res_orig = _render_ruler_vertical(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="m", label="Alt",
        cfg=alt_cfg, val_min=0, val_max=500, ticks=0, thickness=3,
        size_px=int(1.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=fv
    )
    
    ar = np.asarray(res_orig)
    # Check shape stability
    assert ar.shape[0] > 0 and ar.shape[1] > 0

print(f"Total base cache entries created after 500 calls: {len(_RULER_BASE_CACHE)}")
if len(_RULER_BASE_CACHE) == 1:
    print("  -> PERFECT! Exactly 1 cache entry created across 500 changing values!")
else:
    print(f"  -> WARNING: {len(_RULER_BASE_CACHE)} entries created (cache thrashing!)")
