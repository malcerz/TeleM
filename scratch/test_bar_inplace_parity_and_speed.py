import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image, ImageDraw
import numpy as np

from src.indicators.bar import _render_ruler, _render_ruler_vertical, _RULER_BASE_CACHE
from src.indicators.helpers import load_font

layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))
w, h = 3840, 2160
font_path = "arial.ttf"

cfg_dist = layout["indicators"]["fit_distance_text"]
cfg_alt = layout["indicators"]["alt_text"]

print("=" * 90)
print("TESTING IN-PLACE DIRTY RESTORE FOR HORIZONTAL & VERTICAL RULERS")
print("=" * 90)

# 1. Test Horizontal Ruler Parity over 1000 frames
max_diff_h = 0
different_px_h = 0

# Mock InPlace Buffer for Horizontal Ruler
class HorizRulerWorkingBuf:
    def __init__(self, base_img):
        self.img = base_img.copy()
        self.base = base_img
        self.last_dirty = None
    
    def render(self, val_num, val_text, base_data, cfg, canvas_w, canvas_h):
        (
            base, pad_x, width, track_y, marker_radius, marker_border_w, marker_border,
            marker_color, show_value, title_h, title_gap, pad_top, value_font, text_color,
            text_stroke, raster_w, height, ss, val_min, val_max
        ) = base_data
        
        if self.last_dirty is not None:
            bx0, by0, bx1, by1 = self.last_dirty
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

        min_x = marker_x - shadow_r - 4
        max_x = marker_x + shadow_r + 4 + 2 * ss
        min_y = track_y - shadow_r - 4
        max_y = track_y + shadow_r + 4 + 2 * ss

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
            min_x = min(min_x, marker_x + value_offset_x - 180)
            max_x = max(max_x, marker_x + value_offset_x + 180)
            min_y = min(min_y, value_y + value_offset_y - 60)
            max_y = max(max_y, value_y + value_offset_y + 120)

        self.last_dirty = (max(0, min_x), max(0, min_y), min(raster_w, max_x), min(height, max_y))
        return self.img

# Get base_data for horizontal ruler
_render_ruler(
    canvas_w=w, canvas_h=h, font_path=font_path, value=10.0, unit="km",
    label="DISTANCE", cfg=cfg_dist, val_min=0.0, val_max=50.0, ticks=10,
    thickness=3.0, size_px=int(cfg_dist.get("size", 1.0) * 2160 / 100.0),
    fs=24, outline=3, ss=1, formatted_val="10.0 km",
)
static_key_h = [k for k in _RULER_BASE_CACHE.keys() if "bar_ruler_v3" in str(k)][0]
base_data_h = _RULER_BASE_CACHE[static_key_h]
buf_h = HorizRulerWorkingBuf(base_data_h[0])

for i in range(1000):
    val = 0.0 + (i * 0.05) % 50.0
    val_text = f"{val:.1f} km"
    ref_img = _render_ruler(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="km",
        label="DISTANCE", cfg=cfg_dist, val_min=0.0, val_max=50.0, ticks=10,
        thickness=3.0, size_px=int(cfg_dist.get("size", 1.0) * 2160 / 100.0),
        fs=24, outline=3, ss=1, formatted_val=val_text,
    )
    opt_img = buf_h.render(val, val_text, base_data_h, cfg_dist, w, h)
    
    diff = np.abs(np.asarray(ref_img).astype(np.int32) - np.asarray(opt_img).astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_h:
        max_diff_h = md
    different_px_h += int(np.sum(diff > 0) // 4)

print(f"Horizontal Ruler 1000-Frame Parity: MaxDiff={max_diff_h}, DifferentPixels={different_px_h}")
assert max_diff_h == 0, f"Expected 0, got {max_diff_h}"
print("  -> HORIZONTAL RULER PARITY: 100% BIT-FOR-BIT EXACT PASS!")

# 2. Test Vertical Ruler Parity over 1000 frames
class VertRulerWorkingBuf:
    def __init__(self, base_img):
        self.img = base_img.copy()
        self.base = base_img
        self.last_dirty = None
    
    def render(self, val_num, val_text, base_data, cfg, canvas_w, canvas_h):
        (
            base, track_x, top, bottom, track_height, value_x, raster_w, raster_h,
            marker_len, marker_width, marker_color, marker_border, marker_radius, marker_style,
            pixel_profile, shadow_alpha, text_color, text_stroke, value_font,
            ss, lo, hi, show_value, _, legacy_slope, missing,
        ) = base_data
        
        if self.last_dirty is not None:
            bx0, by0, bx1, by1 = self.last_dirty
            patch = self.base.crop((bx0, by0, bx1, by1))
            self.img.paste(patch, (bx0, by0))
        
        d = ImageDraw.Draw(self.img)
        if not missing:
            val_frac = max(0.0, min(1.0, (val_num - lo) / (hi - lo))) if hi > lo else 0.0
            marker_y = int(round(bottom - val_frac * track_height))
            shadow_r = marker_radius + 1 * ss
            d.ellipse(
                (track_x - shadow_r, marker_y - shadow_r, track_x + shadow_r, marker_y + shadow_r),
                fill=(0, 0, 0, shadow_alpha),
            )
            d.ellipse(
                (track_x - marker_radius, marker_y - marker_radius,
                 track_x + marker_radius, marker_y + marker_radius),
                fill=marker_border,
            )
            inner = max(1, marker_radius - max(1, ss))
            d.ellipse(
                (track_x - inner, marker_y - inner, track_x + inner, marker_y + inner),
                fill=marker_color,
            )

            min_x = track_x - shadow_r - 4
            max_x = track_x + shadow_r + 4
            min_y = marker_y - shadow_r - 4
            max_y = marker_y + shadow_r + 4

            if show_value and val_text:
                from src.indicators.bar import _draw_text_bounded
                _draw_text_bounded(
                    d, (value_x, marker_y), val_text,
                    font=value_font, fill=text_color,
                    stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                    bounds=(raster_w, raster_h), anchor="lm",
                )
                min_x = min(min_x, value_x - 10)
                max_x = max(max_x, value_x + 180)
                min_y = min(min_y, marker_y - 40)
                max_y = max(max_y, marker_y + 40)

            self.last_dirty = (max(0, min_x), max(0, min_y), min(raster_w, max_x), min(raster_h, max_y))
        return self.img

_render_ruler_vertical(
    canvas_w=w, canvas_h=h, font_path=font_path, value=250.0, unit="m",
    label="ALTITUDE", cfg=cfg_alt, val_min=0.0, val_max=1000.0, ticks=10,
    thickness=3.0, size_px=int(cfg_alt.get("size", 1.0) * 2160 / 100.0),
    fs=24, outline=3, ss=1, formatted_val="250 m",
)
static_key_v = [k for k in _RULER_BASE_CACHE.keys() if "v3_vertical" in str(k)][0]
base_data_v = _RULER_BASE_CACHE[static_key_v]
buf_v = VertRulerWorkingBuf(base_data_v[0])

max_diff_v = 0
different_px_v = 0
for i in range(1000):
    val = (i * 1.5) % 1000.0
    val_text = f"{val:.0f} m"
    ref_img = _render_ruler_vertical(
        canvas_w=w, canvas_h=h, font_path=font_path, value=val, unit="m",
        label="ALTITUDE", cfg=cfg_alt, val_min=0.0, val_max=1000.0, ticks=10,
        thickness=3.0, size_px=int(cfg_alt.get("size", 1.0) * 2160 / 100.0),
        fs=24, outline=3, ss=1, formatted_val=val_text,
    )
    opt_img = buf_v.render(val, val_text, base_data_v, cfg_alt, w, h)
    diff = np.abs(np.asarray(ref_img).astype(np.int32) - np.asarray(opt_img).astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_v:
        max_diff_v = md
    different_px_v += int(np.sum(diff > 0) // 4)

print(f"Vertical Ruler 1000-Frame Parity: MaxDiff={max_diff_v}, DifferentPixels={different_px_v}")
assert max_diff_v == 0, f"Expected 0, got {max_diff_v}"
print("  -> VERTICAL RULER PARITY: 100% BIT-FOR-BIT EXACT PASS!")
