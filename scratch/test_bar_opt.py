import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
from src.indicators.bar import _render_bar_indicator, _RULER_BASE_CACHE, _static_cache_key

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]

w, h = 3840, 2160
font_path = "arial.ttf"

# Get base data
res_ref = _render_bar_indicator(
    canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
    key="fit_distance_text", value=15.0, unit="km", label="Dystans",
    cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
    val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
    ss=1, formatted_val="15.0 km"
)[0]

# Let's test 3 approaches:
# Approach 0: Reference (current base.copy() + 3 d.ellipse + text)
def run_ref(val):
    return _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="fit_distance_text", value=val, unit="km", label="Dystans",
        cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
        ss=1, formatted_val=f"{val:.1f} km"
    )[0]

# Approach 1: Pre-rendered marker sprite cached + fast paste
# In def_layout.json, show_value is False for fit_distance_text!
# (Notice: show_value is False in def_layout.json for fit_distance_text!)

print("fit_distance_text show_value in def_layout:", dist_cfg.get("show_value"))

t0 = time.perf_counter()
for i in range(300):
    run_ref(i * 0.1)
t_ref = (time.perf_counter() - t0) * 1000.0 / 300.0
print(f"Reference _render_bar_indicator: {t_ref:.3f} ms")
