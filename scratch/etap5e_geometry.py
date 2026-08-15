"""ETAP 5E — compute real layout widget bboxes and check for overlaps."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.indicators.dispatcher import render_value_indicator

CANVAS_W, CANVAS_H = 3840, 2160
FONT = "arial.ttf"

with open("def_layout.json", "r", encoding="utf-8") as f:
    LAYOUT = json.load(f)


def bbox_for(key, cfg, res, rx, ry):
    rotation = int(cfg.get("rotation", 0))
    is_text = cfg.get("form", "text") == "text"
    if is_text:
        if rotation in (90, 270):
            center_x = rx + res.height // 2
            center_y = ry + res.width // 2
        else:
            center_x = rx + res.width // 2
            center_y = ry + res.height // 2
    else:
        center_x, center_y = rx, ry
    if rotation in (90, 270):
        bw, bh = res.height, res.width
    else:
        bw, bh = res.width, res.height
    return (int(center_x - bw // 2), int(center_y - bh // 2), int(bw), int(bh))


boxes = {}
for key, cfg in LAYOUT["indicators"].items():
    if not cfg.get("enabled", True):
        continue
    try:
        res, rx, ry, extra = render_value_indicator(
            CANVAS_W, CANVAS_H, LAYOUT, FONT, key, 87.0, cfg.get("unit", ""),
            cfg.get("label", key), cfg_override=cfg, formatted_val="87",
            history_data=[0.0, 20.0, 50.0, 80.0, 87.0] if cfg.get("form") == "chart" else None,
            current_position=0.5 if cfg.get("form") == "chart" else None,
        )
    except Exception as e:
        print(f"{key:24s} ERROR {e}")
        continue
    if res is None:
        print(f"{key:24s} None")
        continue
    box = bbox_for(key, cfg, res, rx, ry)
    boxes[key] = box
    print(f"{key:24s} bbox={box}  right={box[0]+box[2]} bottom={box[1]+box[3]}")

print("\n--- overlap check (bbox intersections) ---")
keys = list(boxes)
any_overlap = False
for i in range(len(keys)):
    for j in range(i + 1, len(keys)):
        a, b = boxes[keys[i]], boxes[keys[j]]
        if a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
            print(f"OVERLAP: {keys[i]} {a}  <->  {keys[j]} {b}")
            any_overlap = True
if not any_overlap:
    print("No bbox overlaps in layout.")

# also: distance margins (min gap) for annotation-bleed reasoning
print("\n--- min pairwise margin (px) ---")
min_gap = None
for i in range(len(keys)):
    for j in range(i + 1, len(keys)):
        a, b = boxes[keys[i]], boxes[keys[j]]
        dx = max(a[0] - (b[0] + b[2]), b[0] - (a[0] + a[2]), 0)
        dy = max(a[1] - (b[1] + b[3]), b[1] - (a[1] + a[3]), 0)
        gap = (dx or dy) if (dx or dy) else 0
        if min_gap is None or gap < min_gap:
            min_gap = gap
            closest = (keys[i], keys[j])
print("min gap:", min_gap, "between", closest)
