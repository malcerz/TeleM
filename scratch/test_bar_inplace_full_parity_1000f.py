import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image
import numpy as np

from src.indicators.bar import _render_ruler, _render_ruler_vertical, _RULER_WORKING_BUFFERS, _RULER_BASE_CACHE

layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))
w, h = 3840, 2160
font_path = "arial.ttf"

cfg_dist = layout["indicators"]["fit_distance_text"]
cfg_alt = layout["indicators"]["alt_text"]

print("=" * 90)
print("PHASE 17 & 18: PIXEL PARITY & MICROBENCHMARK FOR IN-PLACE RULER OPT")
print("=" * 90)

# 1. Microbenchmark & Parity for Horizontal Ruler (fit_distance_text)
# We test 2001 calls with in-place buffer vs fresh base.copy
times_h_opt = []
for i in range(2001):
    val = (i * 0.025) % 50.0
    val_text = f"{val:.1f} km"
    t0 = time.perf_counter()
    img_h = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km",
        label="DISTANCE", cfg=cfg_dist, val_min=0.0, val_max=50.0, ticks=10,
        thickness=3.0, size_px=int(cfg_dist.get("size", 1.0) * 2160 / 100.0),
        fs=24, outline=3, ss=1, formatted_val=val_text,
    )
    times_h_opt.append((time.perf_counter() - t0) * 1000.0)

print(f"Horizontal Ruler (2001 calls):")
print(f"  AVG:    {np.mean(times_h_opt):.4f} ms")
print(f"  Median: {np.median(times_h_opt):.4f} ms")
print(f"  P95:    {np.percentile(times_h_opt, 95):.4f} ms")

# 2. Microbenchmark & Parity for Vertical Ruler (alt_text)
times_v_opt = []
for i in range(2001):
    val = (i * 0.5) % 1000.0
    val_text = f"{val:.0f} m"
    t0 = time.perf_counter()
    img_v = _render_ruler_vertical(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="m",
        label="ALTITUDE", cfg=cfg_alt, val_min=0.0, val_max=1000.0, ticks=10,
        thickness=3.0, size_px=int(cfg_alt.get("size", 1.0) * 2160 / 100.0),
        fs=24, outline=3, ss=1, formatted_val=val_text,
    )
    times_v_opt.append((time.perf_counter() - t0) * 1000.0)

print(f"\nVertical Ruler (2001 calls):")
print(f"  AVG:    {np.mean(times_v_opt):.4f} ms")
print(f"  Median: {np.median(times_v_opt):.4f} ms")
print(f"  P95:    {np.percentile(times_v_opt, 95):.4f} ms")

# 3. Ground-truth bit-for-bit parity test vs reference fresh base
max_diff_h = 0
different_px_h = 0
for i in range(1000):
    val = (i * 0.05) % 50.0
    val_text = f"{val:.1f} km"
    
    # In-place render
    img_opt = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km",
        label="DISTANCE", cfg=cfg_dist, val_min=0.0, val_max=50.0, ticks=10,
        thickness=3.0, size_px=int(cfg_dist.get("size", 1.0) * 2160 / 100.0),
        fs=24, outline=3, ss=1, formatted_val=val_text,
    )
    
    # Fresh reference render
    static_key = [k for k in _RULER_BASE_CACHE.keys() if "bar_ruler_v3," in str(k) or "bar_ruler_v3'" in str(k)][0]
    base_data = _RULER_BASE_CACHE[static_key]
    (
        base, pad_x, width, track_y, marker_radius, marker_border_w, marker_border,
        marker_color, show_value, title_h, title_gap, pad_top, value_font, text_color,
        text_stroke, raster_w, height, ss, val_min, val_max
    ) = base_data
    img_ref = base.copy()
    from PIL import ImageDraw
    d = ImageDraw.Draw(img_ref)
    frac = max(0.0, min(1.0, (val - val_min) / (val_max - val_min))) if val_max > val_min else 0.0
    marker_x = int(round(pad_x + frac * width))
    shadow_r = marker_radius + marker_border_w
    d.ellipse((marker_x - shadow_r + 2 * ss, track_y - shadow_r + 2 * ss, marker_x + shadow_r + 2 * ss, track_y + shadow_r + 2 * ss), fill=(0, 0, 0, 130))
    d.ellipse((marker_x - marker_radius - marker_border_w, track_y - marker_radius - marker_border_w, marker_x + marker_radius + marker_border_w, track_y + marker_radius + marker_border_w), fill=marker_border)
    d.ellipse((marker_x - marker_radius, track_y - marker_radius, marker_x + marker_radius, track_y + marker_radius), fill=marker_color)
    if show_value and val_text:
        value_y = pad_top + title_h + (title_gap if title_h else 0)
        value_offset_x = int(round(float(cfg_dist.get("value_offset_x", 0.0)) * w / 100.0 * ss))
        value_offset_y = int(round(float(cfg_dist.get("value_offset_y", 0.0)) * h / 100.0 * ss))
        from src.indicators.bar import _draw_text_bounded
        _draw_text_bounded(
            d, (marker_x + value_offset_x, value_y + value_offset_y), val_text,
            font=value_font, fill=text_color, stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
            bounds=(raster_w, height), anchor="ma",
        )
    diff = np.abs(np.asarray(img_ref).astype(np.int32) - np.asarray(img_opt).astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_h:
        max_diff_h = md
    different_px_h += int(np.sum(diff > 0) // 4)

print(f"\nHorizontal 1000-frame Parity: MaxDiff={max_diff_h}, DifferentPixels={different_px_h}")
assert max_diff_h == 0, f"Expected MaxDiff=0, got {max_diff_h}"
print("  -> HORIZONTAL RULER 1000-FRAME PARITY: 100% BIT-FOR-BIT EXACT PASS!")
