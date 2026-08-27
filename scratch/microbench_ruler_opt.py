import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image, ImageDraw
import numpy as np

from src.indicators.bar import _render_ruler, _RULER_BASE_CACHE
from src.indicators.helpers import load_font

layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))
w, h = 3840, 2160
font_path = "arial.ttf"
cfg = layout["indicators"]["fit_distance_text"]

print("=" * 90)
print("MICROBENCHMARK: RULER DYNAMIC PATCH VS FULL COPY")
print("=" * 90)

# Reference 1000 calls
times_ref = []
for i in range(1000):
    val = 10.0 + i * 0.05
    val_text = f"{val:.1f} km"
    t0 = time.perf_counter()
    img_ref = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km",
        label="DISTANCE", cfg=cfg, val_min=0.0, val_max=50.0, ticks=10,
        thickness=3.0, size_px=int(cfg.get("size", 1.0) * 2160 / 100.0),
        fs=24, outline=3, ss=1, formatted_val=val_text,
    )
    times_ref.append((time.perf_counter() - t0) * 1000.0)

print(f"Reference _render_ruler (base.copy):")
print(f"  AVG:    {np.mean(times_ref):.4f} ms")
print(f"  Median: {np.median(times_ref):.4f} ms")
print(f"  P95:    {np.percentile(times_ref, 95):.4f} ms")

# Strategy: Reusable dynamic canvas or Fast buffer copy
# In base.copy(), PIL duplicates 460k pixels.
# If we keep a reusable frame buffer per ruler (or thread-local image buffer of exact size):
# Copying only the previous marker rect + new marker rect is an in-place patch!
# Let's test in-place patch on reusable buffer:

class InPlaceRulerBuffer:
    def __init__(self, base_img):
        self.img = base_img.copy()
        self.base = base_img
        self.last_dirty_box = None
    
    def render(self, val_num, val_text, base_data, cfg, canvas_w, canvas_h):
        (
            base, pad_x, width, track_y, marker_radius, marker_border_w, marker_border,
            marker_color, show_value, title_h, title_gap, pad_top, value_font, text_color,
            text_stroke, raster_w, height, ss, val_min, val_max
        ) = base_data
        
        # 1. Restore only last dirty region from pristine base
        if self.last_dirty_box is not None:
            bx0, by0, bx1, by1 = self.last_dirty_box
            patch = self.base.crop((bx0, by0, bx1, by1))
            self.img.paste(patch, (bx0, by0))
        
        d = ImageDraw.Draw(self.img)
        frac = max(0.0, min(1.0, (val_num - val_min) / (val_max - val_min))) if val_max > val_min else 0.0
        marker_x = int(round(pad_x + frac * width))

        # Marker shadow, border and fill.
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

        dirty_x0 = marker_x - shadow_r - 4
        dirty_x1 = marker_x + shadow_r + 4 + 2 * ss
        dirty_y0 = track_y - shadow_r - 4
        dirty_y1 = track_y + shadow_r + 4 + 2 * ss

        if show_value and val_text:
            value_y = pad_top + title_h + (title_gap if title_h else 0)
            value_offset_x = int(round(float(cfg.get("value_offset_x", 0.0)) * canvas_w / 100.0 * ss))
            value_offset_y = int(round(float(cfg.get("value_offset_y", 0.0)) * canvas_h / 100.0 * ss))
            from src.indicators.bar import _draw_text_bounded
            _draw_text_bounded(
                d, (marker_x + value_offset_x, value_y + value_offset_y), val_text,
                font=value_font, fill=text_color,
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, height), anchor="ma",
            )
            # expand dirty box for text
            dirty_x0 = min(dirty_x0, marker_x + value_offset_x - 150)
            dirty_x1 = max(dirty_x1, marker_x + value_offset_x + 150)
            dirty_y0 = min(dirty_y0, value_y + value_offset_y - 50)
            dirty_y1 = max(dirty_y1, value_y + value_offset_y + 100)

        self.last_dirty_box = (max(0, dirty_x0), max(0, dirty_y0), min(raster_w, dirty_x1), min(height, dirty_y1))
        return self.img

# Get base_data
static_key = list(_RULER_BASE_CACHE.keys())[0] if _RULER_BASE_CACHE else None
base_data = _RULER_BASE_CACHE[static_key]

inplace_buf = InPlaceRulerBuffer(base_data[0])
times_opt = []
for i in range(1000):
    val = 10.0 + i * 0.05
    val_text = f"{val:.1f} km"
    t0 = time.perf_counter()
    img_opt = inplace_buf.render(val, val_text, base_data, cfg, w, h)
    times_opt.append((time.perf_counter() - t0) * 1000.0)

print(f"\nIn-place patched _render_ruler (dirty patch restore):")
print(f"  AVG:    {np.mean(times_opt):.4f} ms")
print(f"  Median: {np.median(times_opt):.4f} ms")
print(f"  P95:    {np.percentile(times_opt, 95):.4f} ms")
print(f"  Speedup: {np.mean(times_ref)/np.mean(times_opt):.2f}x faster!")

# Verify exact bit-for-bit parity
arr_ref = np.asarray(img_ref)
arr_opt = np.asarray(img_opt)
diff = np.abs(arr_ref.astype(np.int32) - arr_opt.astype(np.int32))
max_diff = int(np.max(diff))
different_pixels = int(np.sum(diff > 0) // 4)
print(f"\nExact pixel parity: MaxDiff={max_diff}, DifferentPixels={different_pixels}")
assert max_diff == 0, f"Expected MaxDiff=0, got {max_diff}"
