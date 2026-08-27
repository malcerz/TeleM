import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
from src.indicators.bar import _render_bar_indicator, _RULER_BASE_CACHE, _static_cache_key, _draw_text_bounded_cached

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]

w, h = 3840, 2160
font_path = "arial.ttf"

# Populate cache
_render_bar_indicator(
    canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
    key="fit_distance_text", value=15.0, unit="km", label="Dystans",
    cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
    val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
    ss=1, formatted_val="15.0 km"
)

for k, v in _RULER_BASE_CACHE.items():
    base_data = v
    break

(
    base, pad_x, width, track_y, marker_radius, marker_border_w, marker_border,
    marker_color, show_value, title_h, title_gap, pad_top, value_font, text_color,
    text_stroke, raster_w, height, ss, val_min, val_max
) = base_data

N = 1000

# Timing 1: base.copy()
t0 = time.perf_counter()
for _ in range(N):
    img = base.copy()
t_copy = (time.perf_counter() - t0) * 1000.0 / N

# Timing 2: d = ImageDraw.Draw(img)
img = base.copy()
t0 = time.perf_counter()
for _ in range(N):
    d = ImageDraw.Draw(img)
t_draw_init = (time.perf_counter() - t0) * 1000.0 / N

# Timing 3: d.ellipse (3 ellipses)
t0 = time.perf_counter()
marker_x = 500
shadow_r = marker_radius + marker_border_w
for _ in range(N):
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
t_ellipses = (time.perf_counter() - t0) * 1000.0 / N

# Timing 4: _draw_text_bounded_cached with varying text strings
value_y = pad_top + title_h + (title_gap if title_h else 0)
t0 = time.perf_counter()
for i in range(N):
    _draw_text_bounded_cached(
        img, (marker_x, value_y), f"{i*0.1:.1f} km",
        font=value_font, font_path=font_path, fill=text_color,
        stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
        bounds=(raster_w, height), anchor="ma",
    )
t_text = (time.perf_counter() - t0) * 1000.0 / N

print(f"MICRO-TIMINGS OF RULER STAGES (N={N}):")
print(f"  1. base.copy()                : {t_copy:.4f} ms")
print(f"  2. ImageDraw.Draw(img)        : {t_draw_init:.4f} ms")
print(f"  3. 3x d.ellipse               : {t_ellipses:.4f} ms")
print(f"  4. _draw_text_bounded_cached  : {t_text:.4f} ms")
print(f"  SUM                           : {t_copy + t_draw_init + t_ellipses + t_text:.4f} ms")
