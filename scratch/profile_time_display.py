import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time
from datetime import datetime, timedelta
import numpy as np
from PIL import Image, ImageDraw

from src.indicators.time_display import render_time_display
from src.indicators.helpers import load_font, parse_hex_color, s
from src.indicators.icons import render_icon

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

font_path = ""
canvas_w, canvas_h = 1280, 720

# 1. Measure 120 calls to render_time_display
times = []
for i in range(120):
    t_sec = float(i) / 60.0
    cur_dt = datetime(2026, 8, 14, 11, 18, 10) + timedelta(seconds=t_sec)
    date_str = cur_dt.strftime("%Y.%m.%d")
    time_str = cur_dt.strftime("%H:%M:%S")
    avg_spd = 25.4 + (i % 5) * 0.1
    
    t0 = time.perf_counter()
    img, px_x, px_y = render_time_display(
        canvas_w, canvas_h, layout, font_path,
        date_str, time_str, t_sec, avg_spd
    )
    t1 = time.perf_counter()
    times.append((t1 - t0) * 1000.0)

print(f"Overall render_time_display (120 frames): avg = {sum(times)/len(times):.3f} ms (median = {sorted(times)[60]:.3f} ms)")

# 2. Detailed micro-benchmark of components
cfg = layout.get("indicators", {}).get("time_display")
show_date = cfg.get("show_date", True)
show_time = cfg.get("show_time", True)
show_elapsed = cfg.get("show_elapsed", True)
show_avg_speed = cfg.get("show_avg_speed", True)

t_keys, t_fonts, t_getlength, t_icons, t_img_new, t_draw_text, t_getbbox, t_crop = [], [], [], [], [], [], [], []

for i in range(120):
    t_sec = float(i) / 60.0
    cur_dt = datetime(2026, 8, 14, 11, 18, 10) + timedelta(seconds=t_sec)
    date_text = cur_dt.strftime("%Y.%m.%d")
    time_text = cur_dt.strftime("%H:%M:%S")
    avg_speed_kmh = 25.4 + (i % 5) * 0.1

    # Component 1: cache key + formatting
    t_a = time.perf_counter()
    total = int(t_sec)
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    elapsed_str = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh > 0 else f"{mm:02d}:{ss:02d}"
    avg_speed_str = f"{avg_speed_kmh:.1f} km/h"
    from src.indicators.helpers import _static_cache_key
    ckey = _static_cache_key(
        "time_display", canvas_w, canvas_h, font_path,
        date_text, time_text, elapsed_str, avg_speed_str,
        show_date, show_time, show_elapsed, show_avg_speed, cfg.get("icon", "none")
    )
    t_b = time.perf_counter()
    t_keys.append((t_b - t_a) * 1000.0)

    # Component 2: fonts + getlength
    line_defs = [
        (show_date, date_text, "date", (210, 210, 210), "Data"),
        (show_time, time_text, "time", (255, 255, 255), "Godzina"),
        (show_elapsed, elapsed_str, "elapsed", (255, 255, 255), "Czas"),
        (show_avg_speed, avg_speed_str, "avg_speed", (255, 255, 255), "Średnia prędkość"),
    ]
    min_dim = min(canvas_w, canvas_h)
    outline = max(0, int(round(int(layout["global"].get("text_outline", 3)) * min_dim / 1000)))
    global_fs = max(14, s(cfg.get("font_size", 0.025), min_dim))
    size_mult = cfg.get("size", 0.1) * 10

    t_f0 = time.perf_counter()
    rendered_lines = []
    total_h = outline
    max_w = 0
    for show, text, prefix, default_color, default_label in line_defs:
        if not show or not text: continue
        show_lbl = cfg.get(f"show_{prefix}_label", True)
        lbl = cfg.get(f"{prefix}_label", default_label if show_lbl else "")
        if show_lbl and lbl: text = f"{lbl}: {text}"
        fs = max(1, int(s(cfg.get(f"{prefix}_font_size", global_fs), min_dim) * size_mult))
        font = load_font(font_path, fs)
        color_str = cfg.get(f"{prefix}_color")
        fill = default_color + (255,)
        lh = int(fs * 1.4)
        t_l0 = time.perf_counter()
        tw = int(font.getlength(text) + outline * 4)
        t_l1 = time.perf_counter()
        rendered_lines.append((text, font, lh, fill, tw))
        total_h += lh
        max_w = max(max_w, tw)
    t_f1 = time.perf_counter()
    t_fonts.append((t_f1 - t_f0) * 1000.0)

    # Component 3: icon render
    t_i0 = time.perf_counter()
    icon = render_icon(cfg.get("icon"), max(12, int(global_fs * 0.9)))
    t_i1 = time.perf_counter()
    t_icons.append((t_i1 - t_i0) * 1000.0)

    # Component 4: Image.new
    t_img0 = time.perf_counter()
    tmp_w = int(max(max_w + outline * 2 + (icon.width if icon else 0), s(0.3, canvas_w)))
    tmp_h = max(total_h + outline, 80)
    tmp = Image.new("RGBA", (tmp_w, tmp_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    if icon:
        tmp.alpha_composite(icon, (outline, max(0, (tmp_h - icon.height) // 2)))
    t_img1 = time.perf_counter()
    t_img_new.append((t_img1 - t_img0) * 1000.0)

    # Component 5: draw.text with stroke
    t_dt0 = time.perf_counter()
    y = outline
    for text, font, lh, fill, tw in rendered_lines:
        draw.text(
            (outline + (icon.width if icon else 0), y),
            text, font=font, fill=fill,
            stroke_width=outline, stroke_fill=(0, 0, 0, 255),
        )
        y += lh
    t_dt1 = time.perf_counter()
    t_draw_text.append((t_dt1 - t_dt0) * 1000.0)

    # Component 6: tmp.getbbox()
    t_gb0 = time.perf_counter()
    bbox = tmp.getbbox()
    t_gb1 = time.perf_counter()
    t_getbbox.append((t_gb1 - t_gb0) * 1000.0)

    # Component 7: tmp.crop(bbox)
    t_cr0 = time.perf_counter()
    cropped = tmp.crop(bbox) if bbox else None
    t_cr1 = time.perf_counter()
    t_crop.append((t_cr1 - t_cr0) * 1000.0)

print("\n--- MICRO-TIMINGS BREAKDOWN (avg ms) ---")
print(f"1. Key & string formatting: {sum(t_keys)/len(t_keys):.3f} ms")
print(f"2. Fonts & getlength:       {sum(t_fonts)/len(t_fonts):.3f} ms")
print(f"3. Clock icon render:       {sum(t_icons)/len(t_icons):.3f} ms")
print(f"4. Image.new + composite:   {sum(t_img_new)/len(t_img_new):.3f} ms")
print(f"5. draw.text (4 lines):     {sum(t_draw_text)/len(t_draw_text):.3f} ms")
print(f"6. tmp.getbbox() (alpha):   {sum(t_getbbox)/len(t_getbbox):.3f} ms")
print(f"7. tmp.crop():              {sum(t_crop)/len(t_crop):.3f} ms")
