"""Test Multi-Region HUD grouping algorithm and calculate exact MB/frame transfers.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ffmpeg.command_builder import get_layout_hud_bbox

def compute_indicator_bboxes(layout: dict, canvas_w: int = 3840, canvas_h: int = 2160):
    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])
    boxes = []

    for key, cfg in indicators.items():
        if not cfg or not cfg.get("enabled", True):
            continue
        lx = cfg.get("x", 0.0)
        ly = cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        sz = cfg.get("size", cfg.get("font_size", 10.0))
        sw = int(round((sz / 100.0) * canvas_w)) if sz <= 100.0 else int(round(sz))
        sh = int(round((sz / 100.0) * canvas_h)) if sz <= 100.0 else int(round(sz))

        form = cfg.get("form", "")
        if form in ("chart", "moving_map", "static_map"):
            sw = max(sw, int(canvas_w * 0.45))
            sh = max(sh, int(canvas_h * 0.35))

        x1 = max(0, px - 40)
        y1 = max(0, py - 40)
        x2 = min(canvas_w, px + sw + 60)
        y2 = min(canvas_h, py + sh + 60)
        boxes.append((x1, y1, x2 - x1, y2 - y1, key))

    for idx, ct_cfg in enumerate(custom_texts):
        lx = ct_cfg.get("x", 0.0)
        ly = ct_cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        x1 = max(0, px - 40)
        y1 = max(0, py - 40)
        x2 = min(canvas_w, px + 500)
        y2 = min(canvas_h, py + 150)
        boxes.append((x1, y1, x2 - x1, y2 - y1, f"text_{idx}"))

    return boxes

def group_multi_regions(boxes, canvas_w=3840, canvas_h=2160, max_regions=3):
    if not boxes:
        return []

    # Sort boxes vertically by top y
    boxes = sorted(boxes, key=lambda b: b[1])

    # Simple vertical band clustering: split into Top and Bottom (or Top, Middle, Bottom)
    # Group boxes that overlap or are close in Y (gap < 200px)
    clusters = []
    current_cluster = [boxes[0]]

    for b in boxes[1:]:
        last_b = current_cluster[-1]
        last_y2 = last_b[1] + last_b[3]
        if b[1] <= last_y2 + 300: # merge if vertical gap is less than 300px
            current_cluster.append(b)
        else:
            clusters.append(current_cluster)
            current_cluster = [b]
    clusters.append(current_cluster)

    # Compute bounding box for each cluster
    regions = []
    for cl in clusters:
        min_x = min(b[0] for b in cl)
        min_y = min(b[1] for b in cl)
        max_x = max(b[0] + b[2] for b in cl)
        max_y = max(b[1] + b[3] for b in cl)
        w = max_x - min_x
        h = max_y - min_y
        if min_x % 2 != 0: min_x -= 1
        if min_y % 2 != 0: min_y -= 1
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        regions.append((min_x, min_y, min(canvas_w - min_x, w), min(canvas_h - min_y, h)))

    return regions[:max_regions]

def main():
    with open("def_layout.json", "r", encoding="utf-8") as f:
        normal_layout = json.load(f)

    # 1. Single Bounding Box (Etap 3)
    sb_x, sb_y, sb_w, sb_h = get_layout_hud_bbox(normal_layout, 3840, 2160)
    sb_bytes = sb_w * sb_h * 4
    sb_mb = sb_bytes / (1024 * 1024)

    # 2. Multi-Region Bounding Boxes (Etap 4)
    boxes = compute_indicator_bboxes(normal_layout, 3840, 2160)
    regions = group_multi_regions(boxes, 3840, 2160, max_regions=3)

    mr_bytes = sum(r[2] * r[3] * 4 for r in regions)
    mr_mb = mr_bytes / (1024 * 1024)

    print("=================== HUD BOUNDING BOX COMPARISON ===================")
    print(f"Single Bounding Box: {sb_w}x{sb_h} at ({sb_x},{sb_y}) -> {sb_mb:.2f} MB/frame")
    print(f"Multi-Region Count : {len(regions)}")
    for idx, r in enumerate(regions):
        mb = (r[2] * r[3] * 4) / (1024 * 1024)
        print(f"  Region {idx+1}: {r[2]}x{r[3]} at ({r[0]},{r[1]}) -> {mb:.2f} MB/frame")
    print(f"Multi-Region Total : {mr_mb:.2f} MB/frame")
    print(f"Transfer Reduction : -{((sb_mb - mr_mb) / sb_mb) * 100:.1f}%")
    print("===================================================================")

if __name__ == "__main__":
    main()
