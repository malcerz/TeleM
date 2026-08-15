"""ETAP 5E — ground truth: render real layout widgets, measure content bbox & alpha."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from src.indicators.dispatcher import render_value_indicator

CANVAS_W, CANVAS_H = 3840, 2160
FONT = "arial.ttf"

with open("def_layout.json", "r", encoding="utf-8") as f:
    LAYOUT = json.load(f)

# sample values (only used to render; static widgets don't depend on exact value for bbox)
SAMPLE = {
    "fit_cadence_text": (87.0, "rpm", "Cadence", [0.0, 20.0, 50.0, 80.0, 87.0], 0.5),
    "fit_heart_rate_text": (160.0, "bpm", "HR", [120.0, 140.0, 165.0, 180.0], 0.5),
    "track_map": (0.0, "", "Mapa", None, None),
}


def fmt_bbox(bb):
    if bb is None:
        return "None"
    return (bb[2] - bb[0], bb[3] - bb[1])


for key, cfg in LAYOUT["indicators"].items():
    if not cfg.get("enabled", True):
        continue
    form = cfg.get("form", "text")
    if key in SAMPLE:
        value, unit, label, hist, pos = SAMPLE[key]
    else:
        value, unit, label, hist, pos = 87.0, cfg.get("unit", ""), cfg.get("label", key), None, None
    try:
        res, rx, ry, extra = render_value_indicator(
            CANVAS_W, CANVAS_H, LAYOUT, FONT, key, value, unit, label,
            cfg_override=cfg, formatted_val="87", history_data=hist,
            current_position=pos,
        )
    except Exception as e:
        print(f"{key:24s} ERROR: {e}")
        continue
    if res is None:
        print(f"{key:24s} None")
        continue
    bb = res.getbbox()
    amin, amax = res.getchannel("A").getextrema()
    full = res.width * res.height
    content = (bb[2] - bb[0]) * (bb[3] - bb[1]) if bb else 0
    print(f"{key:24s} size={res.size} bbox={fmt_bbox(bb)} content%={100.0*content/full:5.1f} "
          f"alpha=({amin},{amax}) opaque={amin==255}")
