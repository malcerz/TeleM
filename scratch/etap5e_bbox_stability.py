"""ETAP 5E — getbbox cost + content-bbox stability across frames for gauge/charts."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from src.indicators.dispatcher import render_value_indicator

CANVAS_W, CANVAS_H = 3840, 2160
FONT = "arial.ttf"

with open("def_layout.json", "r", encoding="utf-8") as f:
    LAYOUT = json.load(f)


def bench_getbbox():
    for w, h, name in [(648, 648, "gauge"), (1160, 511, "chart"), (691, 691, "map")]:
        ov = Image.new("RGBA", (w, h), (200, 100, 50, 255))
        iters = 100
        t0 = time.perf_counter()
        for _ in range(iters):
            ov.getbbox()
        ms = (time.perf_counter() - t0) / iters * 1000
        print(f"getbbox {name} {w}x{h}: {ms*1000:.1f}us")


def render(key, value, hist, pos, val_str="87"):
    cfg = dict(LAYOUT["indicators"][key])
    return render_value_indicator(
        CANVAS_W, CANVAS_H, LAYOUT, FONT, key, value, cfg.get("unit", ""),
        cfg.get("label", key), cfg_override=cfg, formatted_val=val_str,
        history_data=hist, current_position=pos,
    )[0]


def bbox_stability():
    # gauge: sweep needle value 0..max
    bb_g = set()
    for v in (0.0, 30.0, 87.0, 140.0):
        im = render("fit_enhanced_speed_text", v, None, None, f"{v:.0f}")
        if im:
            bb_g.add(tuple(im.getbbox() or ()))
    print("gauge bboxes:", bb_g)
    # charts: sweep cursor position 0..1 and value
    bb_c = set()
    for p in (0.0, 0.25, 0.5, 0.99, 1.0):
        im = render("fit_cadence_text", 87.0, [0.0, 20.0, 50.0, 80.0, 87.0], p)
        if im:
            bb_c.add(tuple(im.getbbox() or ()))
    print("cadence bboxes:", bb_c)


bench_getbbox()
bbox_stability()
