import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
from src.indicators.bar import _render_bar_indicator, _RULER_BASE_CACHE, _static_cache_key
from src.indicators.rotated_paste import rotated_paste

layout = json.load(open("def_layout.json", encoding="utf-8"))
dist_cfg = layout["indicators"]["fit_distance_text"]
alt_cfg = layout["indicators"]["alt_text"]

w, h = 3840, 2160
font_path = "arial.ttf"

print("=" * 90)
print("DEEP BREAKDOWN OF BAR RULER STAGES (300 calls)")
print("=" * 90)

# Simulate 300 frames of fit_distance_text and break down every microsecond
times = {
    "render_total": [],
    "paste_total": [],
    "getbbox": [],
    "alpha_composite": [],
}

canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))

for i in range(300):
    val = (i / 300.0) * 45.0
    
    t0 = time.perf_counter()
    res, rx, ry, extra = _render_bar_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="fit_distance_text", value=val, unit="km", label="Dystans",
        cfg=dist_cfg, min_dim=2160, outline=3, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=3, size_px=int(60.0 * 2160 / 100.0),
        ss=1, formatted_val=f"{val:.1f} km"
    )
    t_render = (time.perf_counter() - t0) * 1000.0
    times["render_total"].append(t_render)

    # Now simulate rotated_paste
    t1 = time.perf_counter()
    cx = int(round(dist_cfg["x"] * w / 100.0))
    cy = int(round(dist_cfg["y"] * h / 100.0))
    
    t_bb0 = time.perf_counter()
    ab = res.getchannel("A").getbbox()
    t_bb = (time.perf_counter() - t_bb0) * 1000.0
    times["getbbox"].append(t_bb)

    t_ac0 = time.perf_counter()
    x = int(round(cx - res.width / 2.0))
    y = int(round(cy - res.height / 2.0))
    canvas.alpha_composite(res, (x, y))
    t_ac = (time.perf_counter() - t_ac0) * 1000.0
    times["alpha_composite"].append(t_ac)

    t_paste = (time.perf_counter() - t1) * 1000.0
    times["paste_total"].append(t_paste)

print(f"{'Stage':<30} {'Mean (ms)':<12} {'Median (ms)':<12} {'P95 (ms)':<12}")
print("-" * 90)
for k, v in times.items():
    print(f"{k:<30} {sum(v)/len(v):<12.3f} {sorted(v)[len(v)//2]:<12.3f} {sorted(v)[int(len(v)*0.95)]:<12.3f}")

print(f"\nTotal CPU time for fit_distance_text per frame: {sum(times['render_total'])/len(times['render_total']) + sum(times['paste_total'])/len(times['paste_total']):.3f} ms")
