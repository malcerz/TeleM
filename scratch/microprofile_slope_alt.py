import sys
import json
import time
from pathlib import Path
from collections import defaultdict
import statistics
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.indicators.bar import _render_slope, _render_ruler, _format_slope_number, _draw_text_bounded, _text_size, _line_with_shadow, _fraction
from src.indicators.helpers import load_font, _static_cache_key, _STATIC_CACHE, parse_hex_color

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    v10 = json.load(f)

slope_cfg = v10["indicators"]["slope_text"]
alt_cfg = v10["indicators"]["alt_visual"]

# Detailed micro-profile of _render_slope
slope_breakdown = defaultdict(list)

# We run 200 iterations with representative slope values
values_slope = [1.2, 1.5, 1.8, 2.0, 2.2, 2.5, 2.1, 1.9, 1.7, 1.4] * 20

# Warmup
for v in values_slope[:10]:
    _render_slope(
        canvas_w=1280, canvas_h=720, font_path="", value=v, unit="%", label="SLOPE",
        cfg=slope_cfg, val_min=-20.0, val_max=20.0, thickness=2, size_px=108, fs=9, outline=1, ss=1,
        formatted_val=None
    )

for v in values_slope:
    t0 = time.perf_counter()
    ss = 1
    lo = -20.0
    hi = 20.0
    decimals = 1
    show_label = True
    show_value = True
    show_range = True
    missing = False
    opacity = 1.0
    major_tick = 5.0
    minor_tick = 1.0
    t_cfg = time.perf_counter()
    slope_breakdown["config/key preparation"].append((t_cfg - t0) * 1000.0)

    t0_font = time.perf_counter()
    title_font = load_font("", 8)
    tick_font = load_font("", 7)
    value_font = load_font("", 10)
    text_stroke = 1
    t_font = time.perf_counter()
    slope_breakdown["font lookup"].append((t_font - t0_font) * 1000.0)

    t0_text_m = time.perf_counter()
    title = "SLOPE"
    value_text = f"{_format_slope_number(v, decimals)}%"
    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    # text metrics
    label_width = 18 # approximate or measured
    title_h = 10
    value_width = 30
    t_text_m = time.perf_counter()
    slope_breakdown["text metrics / dummy"].append((t_text_m - t0_text_m) * 1000.0)

    t0_static = time.perf_counter()
    # lookup base
    static_key = ("bar_slope_v1", 100, 200) # representation
    base = _STATIC_CACHE.get(static_key)
    if base is None:
        base = Image.new("RGBA", (80, 150), (0, 0, 0, 0))
        _STATIC_CACHE[static_key] = base
    t_static = time.perf_counter()
    slope_breakdown["static ruler/background lookup"].append((t_static - t0_static) * 1000.0)

    t0_copy = time.perf_counter()
    img = base.copy()
    d = ImageDraw.Draw(img)
    t_copy = time.perf_counter()
    slope_breakdown["copy/allocation"].append((t_copy - t0_copy) * 1000.0)

    t0_marker = time.perf_counter()
    marker_y = 75
    d.line((10, marker_y, 40, marker_y), fill=(255, 212, 42, 255), width=3)
    d.ellipse((20, marker_y - 6, 32, marker_y + 6), fill=(255, 255, 255, 255))
    d.ellipse((21, marker_y - 5, 31, marker_y + 5), fill=(255, 212, 42, 255))
    t_marker = time.perf_counter()
    slope_breakdown["dynamic marker"].append((t_marker - t0_marker) * 1000.0)

    t0_val = time.perf_counter()
    _draw_text_bounded(
        d, (45, marker_y), value_text,
        font=value_font, fill=(255, 255, 255, 255), stroke_width=1,
        stroke_fill=(0, 0, 0, 230), bounds=(80, 150), anchor="lm",
    )
    t_val = time.perf_counter()
    slope_breakdown["current value text"].append((t_val - t0_val) * 1000.0)

print("=== SLOPE INTERNAL MICROPROFILE ===")
for cat, lst in slope_breakdown.items():
    avg = sum(lst) / len(lst)
    print(f"  {cat:32s}: {avg:.4f} ms")


# Detailed micro-profile of _render_ruler (Altitude)
alt_breakdown = defaultdict(list)
values_alt = [250.0, 252.0, 255.0, 260.0, 265.0, 270.0, 268.0, 262.0, 256.0, 251.0] * 20

# Warmup
for v in values_alt[:10]:
    _render_ruler(
        canvas_w=1280, canvas_h=720, font_path="", value=v, unit="m", label="ALTITUDE",
        cfg=alt_cfg, val_min=0.0, val_max=1000.0, ticks=5, thickness=1, size_px=115, fs=9, outline=1, ss=1,
        formatted_val=None
    )

for v in values_alt:
    t0 = time.perf_counter()
    title_fs = 8
    label_fs = 7
    value_fs = 8
    title_font = load_font("", title_fs)
    range_font = load_font("", label_fs)
    value_font = load_font("", value_fs)
    t_font = time.perf_counter()
    alt_breakdown["font lookup"].append((t_font - t0) * 1000.0)

    t0_m = time.perf_counter()
    val_num = v
    value_text = f"{v:.0f} m"
    from src.indicators.bar import _get_ruler_text_metrics
    title_h, range_h, value_h = _get_ruler_text_metrics(
        "", "", title_font, False, "1000 m", range_font, True, value_text, value_font, True, 1
    )
    t_m = time.perf_counter()
    alt_breakdown["metrics cache lookup"].append((t_m - t0_m) * 1000.0)

    t0_bg = time.perf_counter()
    static_key = ("bar_ruler_v2", 100, 200, 300)
    base = _STATIC_CACHE.get(static_key)
    if base is None:
        base = Image.new("RGBA", (150, 60), (0, 0, 0, 0))
        _STATIC_CACHE[static_key] = base
    t_bg = time.perf_counter()
    alt_breakdown["static ruler/background lookup"].append((t_bg - t0_bg) * 1000.0)

    t0_copy = time.perf_counter()
    img = base.copy()
    d = ImageDraw.Draw(img)
    t_copy = time.perf_counter()
    alt_breakdown["copy/allocation"].append((t_copy - t0_copy) * 1000.0)

    t0_marker = time.perf_counter()
    marker_x = 75
    track_y = 30
    shadow_r = 7
    d.ellipse((marker_x - 7, track_y - 7, marker_x + 7, track_y + 7), fill=(0, 0, 0, 130))
    d.ellipse((marker_x - 6, track_y - 6, marker_x + 6, track_y + 6), fill=(255, 255, 255))
    d.ellipse((marker_x - 5, track_y - 5, marker_x + 5, track_y + 5), fill=(0, 170, 255))
    t_marker = time.perf_counter()
    alt_breakdown["dynamic marker"].append((t_marker - t0_marker) * 1000.0)

    t0_val = time.perf_counter()
    _draw_text_bounded(
        d, (marker_x, 10), value_text,
        font=value_font, fill=(255, 255, 255, 255),
        stroke_width=1, stroke_fill=(0, 0, 0, 230),
        bounds=(150, 60), anchor="ma",
    )
    t_val = time.perf_counter()
    alt_breakdown["current value text"].append((t_val - t0_val) * 1000.0)

print("\n=== ALTITUDE INTERNAL MICROPROFILE ===")
for cat, lst in alt_breakdown.items():
    avg = sum(lst) / len(lst)
    print(f"  {cat:32s}: {avg:.4f} ms")
