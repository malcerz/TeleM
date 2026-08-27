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
    _render_bar_indicator,
    _RULER_BASE_CACHE,
    _draw_text_bounded,
    _get_ruler_text_metrics,
    _fraction,
)

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]
alt_cfg = layout["indicators"]["alt_text"]

w, h = 3840, 2160
font_path = "arial.ttf"

print("=" * 90)
print("TESTING IN-PLACE DIRTY RESTORATION SPLIT VS BASE.COPY()")
print("=" * 90)

# Reference rendering of 1000 frames
times_ref = []
for i in range(1000):
    val = (i / 1000.0) * 45.0
    t0 = time.perf_counter()
    img_ref = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km", label="Dystans",
        cfg=dist_cfg, val_min=0, val_max=100, ticks=0, thickness=3,
        size_px=int(60.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=f"{val:.1f} km"
    )
    times_ref.append((time.perf_counter() - t0) * 1000.0)

print(f"Reference _render_ruler (base.copy() each frame, 1000 calls):")
print(f"  Avg:    {np.mean(times_ref):.4f} ms")
print(f"  Median: {np.median(times_ref):.4f} ms")
print(f"  P95:    {np.percentile(times_ref, 95):.4f} ms")

# Now let's implement the In-Place Dirty Restoration Candidate:
# In this pattern, the base cache entry holds:
# (base, work_img, prev_dirty_box, ...)
# On each frame:
# 1. If prev_dirty_box is not None:
#    work_img.paste(base.crop(prev_dirty_box), (prev_dirty_box[0], prev_dirty_box[1]))
# 2. Draw marker & text on work_img
# 3. Compute new_dirty_box
# 4. Return work_img

for k, v in _RULER_BASE_CACHE.items():
    base_data = v
    break

(
    base, pad_x, width, track_y, marker_radius, marker_border_w, marker_border,
    marker_color, show_value, title_h, title_gap, pad_top, value_font, text_color,
    text_stroke, raster_w, height, ss, val_min, val_max
) = base_data

work_img = base.copy()
prev_box = None

times_cand = []
max_diff = 0
total_diff_px = 0

for i in range(1000):
    val = (i / 1000.0) * 45.0
    val_text = f"{val:.1f} km"
    
    t0 = time.perf_counter()
    
    # 1. Restore previous dirty region if any
    if prev_box is not None:
        px0, py0, px1, py1 = prev_box
        patch = base.crop((px0, py0, px1, py1))
        work_img.paste(patch, (px0, py0))
    
    # 2. Draw dynamic marker & value
    d = ImageDraw.Draw(work_img)
    frac = _fraction(val, val_min, val_max)
    marker_x = int(round(pad_x + frac * width))
    shadow_r = marker_radius + marker_border_w

    d.ellipse(
        (marker_x - shadow_r + 2 * ss, track_y - shadow_r + 2 * ss,
         marker_x + shadow_r + 2 * ss, track_y + shadow_r + 2 * ss),
        fill=(0, 0, 0, 130),
    )
    d.ellipse(
        (marker_x - marker_radius - marker_border_w, track_y - marker_radius - marker_border_w,
         marker_x + marker_radius + marker_border_w, track_y + marker_radius + marker_border_w),
        fill=marker_border,
    )
    d.ellipse(
        (marker_x - marker_radius, track_y - marker_radius,
         marker_x + marker_radius, track_y + marker_radius),
        fill=marker_color,
    )

    if show_value and val_text:
        value_y = pad_top + title_h + (title_gap if title_h else 0)
        _draw_text_bounded(
            d, (marker_x, value_y), val_text,
            font=value_font, fill=text_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
            bounds=(raster_w, height), anchor="ma",
        )
    
    # 3. Compute dirty box bounds (marker radius + text bounds + pad)
    pad = 4 * ss
    bx0 = max(0, marker_x - shadow_r - 2 * ss - 80)
    by0 = max(0, min(track_y - shadow_r, value_y - 20))
    bx1 = min(raster_w, marker_x + shadow_r + 2 * ss + 80)
    by1 = min(height, track_y + shadow_r + 2 * ss + 10)
    prev_box = (bx0, by0, bx1, by1)
    
    t_el = (time.perf_counter() - t0) * 1000.0
    times_cand.append(t_el)

    # Check parity with reference on this frame
    ref_img = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km", label="Dystans",
        cfg=dist_cfg, val_min=0, val_max=100, ticks=0, thickness=3,
        size_px=int(60.0 * 2160 / 100.0), fs=24, outline=3, ss=1, formatted_val=val_text
    )
    ar = np.asarray(ref_img)
    ac = np.asarray(work_img)
    diff = np.abs(ar.astype(np.int32) - ac.astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff:
        max_diff = md
    total_diff_px += int(np.sum(np.any(diff > 0, axis=-1)))

print(f"\nCandidate in-place restoration (1000 calls):")
print(f"  Avg:    {np.mean(times_cand):.4f} ms")
print(f"  Median: {np.median(times_cand):.4f} ms")
print(f"  P95:    {np.percentile(times_cand, 95):.4f} ms")
print(f"\nParity Verification:")
print(f"  Max Diff:         {max_diff}")
print(f"  Different Pixels: {total_diff_px}")
if max_diff == 0:
    print("  -> 100% BIT-FOR-BIT EXACT PARITY PASSED! ZERO GHOSTING!")
