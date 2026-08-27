import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from src.indicators.bar import _render_ruler, _render_ruler_vertical, _render_bar_indicator

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]
alt_cfg = layout["indicators"]["alt_text"]

w, h = 3840, 2160
font_path = "arial.ttf"

# 1. Test Horizontal Ruler Parity
print("=" * 80)
print("TESTING PRE-RENDERED MARKER SPRITE PARITY (HORIZONTAL RULER)")
print("=" * 80)

# Reference implementation on value 15.35
res_ref = _render_bar_indicator(
    canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
    key="fit_distance_text", value=15.35, unit="km", label="Dystans",
    cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
    val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
    ss=1, formatted_val="15.4 km"
)[0]

# Candidate implementation: pre-render marker sprite into an RGBA tile once, then composite
# Let's see the geometry of marker in _render_ruler:
ss = 1
marker_radius = max(3 * ss, int(round(float(dist_cfg.get("marker_size", 7)) * ss)))
marker_border_w = max(1 * ss, int(round(float(dist_cfg.get("marker_border_width", 1.5)) * ss)))
shadow_r = marker_radius + marker_border_w
tile_r = shadow_r + 2 * ss  # extra 2px for shadow offset
tile_size = 2 * tile_r + 1

marker_tile = Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
d_m = ImageDraw.Draw(marker_tile)
cx_m, cy_m = tile_r, tile_r

# Draw shadow, border, fill exactly as in _render_ruler:
d_m.ellipse(
    (cx_m - shadow_r + 2 * ss, cy_m - shadow_r + 2 * ss,
     cx_m + shadow_r + 2 * ss, cy_m + shadow_r + 2 * ss),
    fill=(0, 0, 0, 130),
)
d_m.ellipse(
    (cx_m - marker_radius - marker_border_w, cy_m - marker_radius - marker_border_w,
     cx_m + marker_radius + marker_border_w, cy_m + marker_radius + marker_border_w),
    fill=(216, 216, 216, 255),
)
d_m.ellipse(
    (cx_m - marker_radius, cy_m - marker_radius,
     cx_m + marker_radius, cy_m + marker_radius),
    fill=(21, 159, 165, 255),
)

# Now test candidate render on identical base:
from src.indicators.bar import _RULER_BASE_CACHE

# Get base from cache
for k, v in _RULER_BASE_CACHE.items():
    base_data = v
    break

(
    base, pad_x, width, track_y, _mr, _mbw, _mb, _mc, show_value, title_h, title_gap,
    pad_top, value_font, text_color, text_stroke, raster_w, height, ss, val_min, val_max
) = base_data

img_cand = base.copy()
val_num = 15.35
frac = (val_num - val_min) / (val_max - val_min)
marker_x = int(round(pad_x + frac * width))

# Paste pre-rendered marker tile
img_cand.alpha_composite(marker_tile, (marker_x - cx_m, track_y - cy_m))

# Draw value text
from src.indicators.bar import _draw_text_bounded_cached
value_y = pad_top + title_h + (title_gap if title_h else 0)
_draw_text_bounded_cached(
    img_cand, (marker_x, value_y), "15.4 km",
    font=value_font, font_path=font_path, fill=text_color,
    stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
    bounds=(raster_w, height), anchor="ma",
)

# Compare res_ref vs img_cand
arr_ref = np.asarray(res_ref)
arr_cand = np.asarray(img_cand)
diff = np.abs(arr_ref.astype(np.int32) - arr_cand.astype(np.int32))
max_diff = int(np.max(diff))
diff_px = int(np.sum(np.any(diff > 0, axis=-1)))
mae = float(np.mean(diff))

print(f"Comparison Results:")
print(f"  Max Diff:         {max_diff}")
print(f"  Different Pixels: {diff_px}")
print(f"  MAE:              {mae:.6f}")
if max_diff == 0:
    print("  -> EXACT 100% BIT-FOR-BIT MATCH!")
else:
    print(f"  -> Differs on {diff_px} pixels")
