import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time
from PIL import Image, ImageDraw
import numpy as np

from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import load_font, parse_hex_color, s
from src.indicators.bar import (
    _render_ruler, _rgb, _rgba, _clamp01, _fraction, _fmt_number,
    _text_size, _draw_text_bounded, _line_with_shadow
)

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720
font_path = ""
dist_cfg = layout["indicators"]["dist_visual"]

# Measure overall time for 120 calls
times = []
for i in range(120):
    val = 2.45 + (i % 5) * 0.05
    fv = f"{val:.1f} km"
    t0 = time.perf_counter()
    img, x, y, _ = render_value_indicator(
        canvas_w, canvas_h, layout, font_path,
        "dist_visual", val, "km", dist_cfg.get("label", ""),
        cfg_override=dist_cfg,
        formatted_val=fv,
        supersample=1,
    )
    t1 = time.perf_counter()
    times.append((t1 - t0) * 1000.0)

print(f"Overall Distance (120 frames): avg = {sum(times)/len(times):.3f} ms (median = {sorted(times)[60]:.3f} ms, p95 = {sorted(times)[114]:.3f} ms)")

# Micro-breakdown
t_measure, t_base_fetch, t_copy, t_marker, t_val_text = [], [], [], [], []

for i in range(120):
    val = 2.45 + (i % 5) * 0.05
    formatted_val = f"{val:.1f} km"
    cfg = dist_cfg
    min_dim = min(canvas_w, canvas_h)
    size_px = s(cfg.get("size", 10.0), canvas_w)
    fs = max(10, s(cfg.get("font_size", 1.0), min_dim))
    outline = max(0, int(round(int(layout["global"].get("text_outline", 3)) * min_dim / 1000)))
    val_min = cfg.get("min_val", 0.0)
    val_max = cfg.get("max_val", 10.0)
    label = cfg.get("label", "")
    unit = cfg.get("unit", "km")
    ss = 1
    width = max(80 * ss, int(size_px * ss))

    # 1. Fonts & text metrics
    t0 = time.perf_counter()
    title_fs = max(8 * ss, int(round(float(cfg.get("title_font_scale", 1.00)) * fs * ss)))
    label_fs = max(7 * ss, int(round(float(cfg.get("range_font_scale", 0.82)) * fs * ss)))
    value_fs = max(8 * ss, int(round(float(cfg.get("value_font_scale", 1.00)) * fs * ss)))
    title_font = load_font(font_path, title_fs)
    range_font = load_font(font_path, label_fs)
    value_font = load_font(font_path, value_fs)
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    show_title = bool(cfg.get("show_label", True))
    show_range = bool(cfg.get("show_range_labels", True))
    show_mid = bool(cfg.get("show_mid_label", True))
    show_value = bool(cfg.get("show_value", False))
    range_units = bool(cfg.get("range_units", True))
    title_with_unit = bool(cfg.get("title_with_unit", True))
    uppercase_title = bool(cfg.get("uppercase_title", True))
    decimals = int(cfg.get("decimals", 0))

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    title = ""
    title_h = 0
    range_sample = f"{_fmt_number(max(abs(val_min), abs(val_max)), decimals)} {unit}".strip()
    range_h = _text_size(dd, range_sample, range_font, text_stroke)[1] if show_range else 0
    value_text = formatted_val if formatted_val is not None else f"{_fmt_number(val, decimals)} {unit}".strip()
    value_h = _text_size(dd, value_text, value_font, text_stroke)[1] if show_value else 0
    t1 = time.perf_counter()
    t_measure.append((t1 - t0) * 1000.0)

    # 2. Key & Base fetch
    pixel_profile = str(cfg.get("tick_profile", "default")).strip().lower() == "pixel"
    tick_w = max(1 * ss, int(round(float(cfg.get("tick_width", 1.4)) * ss)))
    major_len = max(8 * ss, int(round(width * 0.040))) if pixel_profile else max(8 * ss, int(round(float(cfg.get("major_tick_length", 17)) * ss)))
    minor_len = max(4 * ss, int(round(width * 0.018))) if pixel_profile else max(4 * ss, int(round(float(cfg.get("minor_tick_length", 10)) * ss)))
    marker_radius = max(3 * ss, int(round(float(cfg.get("marker_size", 7)) * ss)))
    marker_border_w = max(1 * ss, int(round(float(cfg.get("marker_border_width", 1.5)) * ss)))

    pad_x = max(marker_radius + 4 * ss, 8 * ss)
    pad_top = 4 * ss
    title_gap = 5 * ss if title_h else 0
    value_gap = 4 * ss if value_h else 0
    track_y = pad_top + title_h + title_gap + value_h + value_gap + major_len + marker_radius
    bottom_gap = 6 * ss
    height = int(track_y + marker_radius + bottom_gap + range_h + 5 * ss)
    raster_w = width + pad_x * 2

    # Render base once or get
    base = _render_ruler(
        canvas_w=canvas_w, canvas_h=canvas_h, font_path=font_path,
        value=val, unit=unit, label=label, cfg=cfg,
        val_min=val_min, val_max=val_max, ticks=5, thickness=1,
        size_px=size_px, fs=fs, outline=outline, ss=ss, formatted_val=formatted_val
    )
    t2 = time.perf_counter()
    t_base_fetch.append((t2 - t1) * 1000.0)

    # 3. Base copy
    img = base.copy()
    d = ImageDraw.Draw(img)
    t3 = time.perf_counter()
    t_copy.append((t3 - t2) * 1000.0)

    # 4. Marker ellipses
    frac = _fraction(val, val_min, val_max)
    marker_x = int(round(pad_x + frac * width))
    shadow_r = marker_radius + marker_border_w
    d.ellipse((marker_x - shadow_r + 2 * ss, track_y - shadow_r + 2 * ss, marker_x + shadow_r + 2 * ss, track_y + shadow_r + 2 * ss), fill=(0, 0, 0, 130))
    d.ellipse((marker_x - marker_radius - marker_border_w, track_y - marker_radius - marker_border_w, marker_x + marker_radius + marker_border_w, track_y + marker_radius + marker_border_w), fill=(216, 216, 216, 255))
    d.ellipse((marker_x - marker_radius, track_y - marker_radius, marker_x + marker_radius, track_y + marker_radius), fill=(255, 212, 42, 255))
    t4 = time.perf_counter()
    t_marker.append((t4 - t3) * 1000.0)

    # 5. Value text draw
    if show_value and value_text:
        value_y = pad_top + title_h + (title_gap if title_h else 0)
        value_offset_x = 0
        value_offset_y = 0
        _draw_text_bounded(
            d, (marker_x + value_offset_x, value_y + value_offset_y), value_text,
            font=value_font, fill=(255, 255, 255, 255),
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
            bounds=(raster_w, height), anchor="ma",
        )
    t5 = time.perf_counter()
    t_val_text.append((t5 - t4) * 1000.0)

print("\n--- DISTANCE MICRO-TIMINGS BREAKDOWN (avg ms) ---")
print(f"1. Text metrics (_text_size): {sum(t_measure)/len(t_measure):.3f} ms")
print(f"2. Base image copy:           {sum(t_copy)/len(t_copy):.3f} ms")
print(f"3. Marker ellipses (x3):      {sum(t_marker)/len(t_marker):.3f} ms")
print(f"4. Value draw.text with stroke: {sum(t_val_text)/len(t_val_text):.3f} ms")
