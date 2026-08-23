import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time
from PIL import Image, ImageDraw
import numpy as np

from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import load_font, parse_hex_color, s
from src.indicators.icons import render_icon
from src.indicators.bar import (
    _render_segments, _rgb, _rgba, _clamp01, _fraction, _fmt_number,
    _gradient_colour, _text_size, _draw_text_bounded
)

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720
font_path = ""

bat_cfg = layout["indicators"]["fit_battery_pct_text"]
sol_cfg = layout["indicators"]["fit_solar_pct_text"]

def benchmark_widget(key, val_fn):
    times = []
    cfg = layout["indicators"][key]
    for i in range(120):
        val = val_fn(i)
        fv = f"{int(val)}%" if val is not None else "--"
        t0 = time.perf_counter()
        img, x, y, _ = render_value_indicator(
            canvas_w, canvas_h, layout, font_path,
            key, val, cfg.get("unit", "%"), cfg.get("label", ""),
            cfg_override=cfg,
            formatted_val=fv,
            supersample=1,
        )
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return times

bat_times = benchmark_widget("fit_battery_pct_text", lambda i: 89.0 - (i % 2) * 1.0)
sol_times = benchmark_widget("fit_solar_pct_text", lambda i: 100.0 if i < 60 else 0.0)

print(f"Overall Battery (120 frames): avg = {sum(bat_times)/len(bat_times):.3f} ms (median = {sorted(bat_times)[60]:.3f} ms, p95 = {sorted(bat_times)[114]:.3f} ms)")
print(f"Overall Solar   (120 frames): avg = {sum(sol_times)/len(sol_times):.3f} ms (median = {sorted(sol_times)[60]:.3f} ms, p95 = {sorted(sol_times)[114]:.3f} ms)")
print(f"Overall SUM:                  avg = {(sum(bat_times)+sum(sol_times))/len(bat_times):.3f} ms")

# Micro-breakdown for Battery and Solar
def profile_segments_micro(cfg, key, value, formatted_val):
    min_dim = min(canvas_w, canvas_h)
    size_px = s(cfg.get("size", 10.0), canvas_w)
    fs = max(10, s(cfg.get("font_size", 1.0), min_dim))
    outline = max(0, int(round(int(layout["global"].get("text_outline", 3)) * min_dim / 1000)))
    val_min = cfg.get("min_val", 0.0)
    val_max = cfg.get("max_val", 100.0)
    label = cfg.get("label", "")
    unit = cfg.get("unit", "%")

    t_font, t_measure, t_alloc, t_inactive_segs, t_active_segs, t_val_text, t_label_text, t_icon, t_composite = [], [], [], [], [], [], [], [], []

    for i in range(120):
        # 1. Fonts
        t0 = time.perf_counter()
        ss = 1
        width = max(80 * ss, int(size_px * ss))
        segments = max(2, int(cfg.get("segments", 20)))
        gap = max(0, int(round(float(cfg.get("segment_gap", 3)) * ss)))
        radius = max(0, int(round(float(cfg.get("segment_radius", 1)) * ss)))
        decimals = max(0, int(cfg.get("decimals", 1)))

        value_fs = max(10 * ss, int(round(float(cfg.get("value_font_scale", 1.70)) * fs * ss)))
        label_fs = max(7 * ss, int(round(float(cfg.get("label_font_scale", 0.72)) * fs * ss)))
        range_fs = max(7 * ss, int(round(float(cfg.get("range_font_scale", 0.82)) * fs * ss)))
        value_font = load_font(font_path, value_fs)
        label_font = load_font(font_path, label_fs)
        range_font = load_font(font_path, range_fs)
        text_stroke = max(0, int(round(max(1, outline) * ss)))
        t1 = time.perf_counter()
        t_font.append((t1 - t0) * 1000.0)

        # 2. Text metrics
        dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dummy)
        value_text = str(formatted_val) if formatted_val is not None else _fmt_number(value, decimals)
        value_h = _text_size(dd, value_text, value_font, text_stroke)[1]
        label_h = _text_size(dd, str(label), label_font, text_stroke)[1] if label else 0
        t2 = time.perf_counter()
        t_measure.append((t2 - t1) * 1000.0)

        # 3. Allocation
        pad_x = 4 * ss
        top_pad = 3 * ss
        value_gap = 3 * ss if value_h else 0
        bottom_text_h = label_h
        bottom_pad = 3 * ss
        seg_area_h = max(16 * ss, int(round(width * float(cfg.get("segment_height_ratio", 0.105)))))
        raster_w = width + pad_x * 2
        raster_h = int(top_pad + value_h + value_gap + seg_area_h + 5 * ss + bottom_text_h + bottom_pad)
        seg_top = top_pad + value_h + value_gap
        seg_bottom = seg_top + seg_area_h
        img = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        t3 = time.perf_counter()
        t_alloc.append((t3 - t2) * 1000.0)

        # 4. Geometry & Inactive segments + Active segments
        total_gap = gap * (segments - 1)
        seg_w = (width - total_gap) / segments
        frac = _fraction(value, val_min, val_max)
        active = 0 if frac <= 0.0 else min(segments, int(np.ceil(frac * segments - 1e-12)))
        inactive_alpha = max(0, min(255, int(cfg.get("inactive_alpha", 95))))
        inactive = _rgba(cfg.get("inactive_color", "#3E3E3E"), (62, 62, 62), inactive_alpha)
        gradient = cfg.get("gradient", ["#16A7AF", "#08B86B", "#13C630", "#C8D923", "#FFD42A", "#FF9A2E"])
        grow_start = _clamp01(float(cfg.get("grow_start", 0.55)))
        grow_height = bool(cfg.get("grow_height", True))

        t_in_0 = time.perf_counter()
        # Draw inactive segments
        for idx in range(segments):
            p = idx / max(1, segments - 1)
            h_mult = grow_start + (1.0 - grow_start) * p if grow_height else 1.0
            sh = max(2 * ss, int(round(seg_area_h * h_mult)))
            x1 = int(round(pad_x + idx * (seg_w + gap)))
            x2 = int(round(pad_x + idx * (seg_w + gap) + seg_w - 1))
            y2 = seg_bottom
            y1 = y2 - sh
            shadow_off = max(1, ss)
            d.rounded_rectangle((x1 + shadow_off, y1 + shadow_off, x2 + shadow_off, y2 + shadow_off), radius=radius, fill=(0, 0, 0, 75))
            if idx >= active:
                d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=inactive)
        t_in_1 = time.perf_counter()
        t_inactive_segs.append((t_in_1 - t_in_0) * 1000.0)

        # Draw active segments
        t_ac_0 = time.perf_counter()
        for idx in range(active):
            p = idx / max(1, segments - 1)
            h_mult = grow_start + (1.0 - grow_start) * p if grow_height else 1.0
            sh = max(2 * ss, int(round(seg_area_h * h_mult)))
            x1 = int(round(pad_x + idx * (seg_w + gap)))
            x2 = int(round(pad_x + idx * (seg_w + gap) + seg_w - 1))
            y2 = seg_bottom
            y1 = y2 - sh
            colour = _gradient_colour(gradient, p)
            fill = (*colour, 255)
            d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill)
        t_ac_1 = time.perf_counter()
        t_active_segs.append((t_ac_1 - t_ac_0) * 1000.0)

        # 5. Value text draw
        text_color = _rgba(cfg.get("text_color", "#FFFFFF"), (255, 255, 255), 255)
        t_vt_0 = time.perf_counter()
        _draw_text_bounded(
            d, (pad_x, top_pad), value_text,
            font=value_font, fill=text_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor="la",
        )
        t_vt_1 = time.perf_counter()
        t_val_text.append((t_vt_1 - t_vt_0) * 1000.0)

        # 6. Label & icon
        t_lb_0 = time.perf_counter()
        bottom_y = seg_bottom + 5 * ss
        icon = render_icon(cfg.get("icon"), max(10 * ss, int(label_fs * 1.1)))
        if icon:
            ix = max(0, int((raster_w - icon.width - int(label_font.getlength(str(label)))) / 2) - 3 * ss)
            iy = max(0, int(bottom_y + (bottom_text_h - icon.height) / 2))
            img.alpha_composite(icon, (ix, iy))
        _draw_text_bounded(
            d, (raster_w / 2, bottom_y), str(label).upper() if cfg.get("uppercase_label", True) else str(label),
            font=label_font, fill=text_color,
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 220),
            bounds=(raster_w, raster_h), anchor="ma",
        )
        t_lb_1 = time.perf_counter()
        t_label_text.append((t_lb_1 - t_lb_0) * 1000.0)

    return {
        "font": sum(t_font) / len(t_font),
        "measure": sum(t_measure) / len(t_measure),
        "alloc": sum(t_alloc) / len(t_alloc),
        "inactive_segs": sum(t_inactive_segs) / len(t_inactive_segs),
        "active_segs": sum(t_active_segs) / len(t_active_segs),
        "val_text": sum(t_val_text) / len(t_val_text),
        "label_and_icon": sum(t_label_text) / len(t_label_text),
    }

bat_prof = profile_segments_micro(bat_cfg, "fit_battery_pct_text", 89.0, "89%")
sol_prof = profile_segments_micro(sol_cfg, "fit_solar_pct_text", 100.0, "100%")

print("\n--- MICRO-TIMINGS BREAKDOWN (avg ms) ---")
print(f"{'Stage':20} | {'Battery ms':>10} | {'Solar ms':>10}")
print("-" * 46)
print(f"{'font lookup':20} | {bat_prof['font']:10.3f} | {sol_prof['font']:10.3f}")
print(f"{'text metrics':20} | {bat_prof['measure']:10.3f} | {sol_prof['measure']:10.3f}")
print(f"{'allocation/ImageDraw':20} | {bat_prof['alloc']:10.3f} | {sol_prof['alloc']:10.3f}")
print(f"{'inactive segs+shadow':20} | {bat_prof['inactive_segs']:10.3f} | {sol_prof['inactive_segs']:10.3f}")
print(f"{'active segs':20} | {bat_prof['active_segs']:10.3f} | {sol_prof['active_segs']:10.3f}")
print(f"{'draw.text (value)':20} | {bat_prof['val_text']:10.3f} | {sol_prof['val_text']:10.3f}")
print(f"{'label + icon':20} | {bat_prof['label_and_icon']:10.3f} | {sol_prof['label_and_icon']:10.3f}")
