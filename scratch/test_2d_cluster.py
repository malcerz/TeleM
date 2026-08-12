"""Test 2D bounding box clustering algorithm for HUD layouts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ffmpeg.command_builder import get_layout_hud_bbox

def compute_indicator_boxes(layout: dict, canvas_w=3840, canvas_h=2160):
    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])
    enabled = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}

    boxes = []
    for key, cfg in enabled.items():
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

        x1 = max(0, px - 30)
        y1 = max(0, py - 30)
        x2 = min(canvas_w, px + sw + 40)
        y2 = min(canvas_h, py + sh + 40)
        boxes.append([x1, y1, x2, y2, key])

    for idx, ct in enumerate(custom_texts):
        lx = ct.get("x", 0.0)
        ly = ct.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        boxes.append([max(0, px - 30), max(0, py - 30), min(canvas_w, px + 500), min(canvas_h, py + 150), f"text_{idx}"])

    return boxes

def box_area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])

def merge_boxes(b1, b2):
    return [
        min(b1[0], b2[0]),
        min(b1[1], b2[1]),
        max(b1[2], b2[2]),
        max(b1[3], b2[3]),
    ]

def cluster_2d_regions(boxes, canvas_w=3840, canvas_h=2160, max_regions=2):
    if not boxes:
        return [(0, 0, 2, 2)]

    clusters = [[b[0], b[1], b[2], b[3]] for b in boxes]

    while len(clusters) > max_regions:
        best_pair = None
        best_waste = float("inf")

        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                mb = merge_boxes(clusters[i], clusters[j])
                ma = box_area(mb)
                a1 = box_area(clusters[i])
                a2 = box_area(clusters[j])
                waste = ma - (a1 + a2)
                if waste < best_waste:
                    best_waste = waste
                    best_pair = (i, j)

        if best_pair is None:
            break

        i, j = best_pair
        new_b = merge_boxes(clusters[i], clusters[j])
        clusters.pop(j)
        clusters.pop(i)
        clusters.append(new_b)

    results = []
    for c in clusters:
        x1, y1, x2, y2 = c
        w = max(2, x2 - x1)
        h = max(2, y2 - y1)
        if x1 % 2 != 0: x1 -= 1
        if y1 % 2 != 0: y1 -= 1
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        results.append((x1, y1, min(canvas_w - x1, w), min(canvas_h - y1, h)))

    return results

def main():
    with open("def_layout.json", "r", encoding="utf-8") as f:
        normal_layout = json.load(f)

    # Single Bbox
    sb_x, sb_y, sb_w, sb_h = get_layout_hud_bbox(normal_layout, 3840, 2160)
    sb_mb = (sb_w * sb_h * 4) / (1024 * 1024)

    boxes = compute_indicator_boxes(normal_layout, 3840, 2160)
    for mr in (2, 3, 4):
        regions = cluster_2d_regions(boxes, 3840, 2160, max_regions=mr)
        total_mb = sum((r[2] * r[3] * 4) / (1024 * 1024) for r in regions)
        print(f"\n2D Cluster Regions ({mr} regions) : Total {total_mb:.2f} MB/frame (Reduction: -{((sb_mb - total_mb) / sb_mb) * 100:.1f}%)")
        for idx, r in enumerate(regions):
            mb = (r[2] * r[3] * 4) / (1024 * 1024)
            print(f"  Region {idx+1}: {r[2]}x{r[3]} at ({r[0]},{r[1]}) -> {mb:.2f} MB/frame")

if __name__ == "__main__":
    main()
