import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw

from src.indicators.bar import _render_ruler, _render_ruler_vertical, _render_bar_indicator
from src.indicators.helpers import load_font

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]
alt_cfg = layout["indicators"]["alt_text"]

print("=" * 80)
print("MICROBENCHMARK: Bar Indicators in def_layout.json")
print("=" * 80)

# 1. fit_distance_text
w, h = 3840, 2160
font_path = "arial.ttf"

times_dist = []
for i in range(300):
    val = (i / 300.0) * 45.0
    t0 = time.perf_counter()
    img = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="fit_distance_text", value=val, unit="km", label="Dystans",
        cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
        ss=1, formatted_val=f"{val:.1f} km"
    )
    times_dist.append((time.perf_counter() - t0) * 1000.0)

print(f"fit_distance_text (horizontal ruler):")
print(f"  size: {img[0].size}")
print(f"  avg:    {sum(times_dist)/len(times_dist):.3f} ms")
print(f"  median: {sorted(times_dist)[len(times_dist)//2]:.3f} ms")
print(f"  p95:    {sorted(times_dist)[int(len(times_dist)*0.95)]:.3f} ms")

# 2. alt_text (vertical ruler)
times_alt = []
for i in range(300):
    val = 150.0 + i * 0.5
    t0 = time.perf_counter()
    img = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="alt_text", value=val, unit="m", label="Alt",
        cfg=alt_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=500, ticks=0, thickness=3, size_px=int(1.0 * 2160 / 100.0),
        ss=1, formatted_val=f"{val:.0f} m"
    )
    times_alt.append((time.perf_counter() - t0) * 1000.0)

print(f"\nalt_text (vertical ruler):")
print(f"  size: {img[0].size}")
print(f"  avg:    {sum(times_alt)/len(times_alt):.3f} ms")
print(f"  median: {sorted(times_alt)[len(times_alt)//2]:.3f} ms")
print(f"  p95:    {sorted(times_alt)[int(len(times_alt)*0.95)]:.3f} ms")
