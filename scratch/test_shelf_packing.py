"""Test 2D Shelf Packing for HUD atlas regions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scratch.test_2d_cluster import compute_indicator_boxes, cluster_2d_regions

def compute_shelf_atlas(layout: dict[str, Any], canvas_w: int = 3840, canvas_h: int = 2160, max_regions: int = 3):
    boxes = compute_indicator_boxes(layout, canvas_w, canvas_h)
    clusters = cluster_2d_regions(boxes, canvas_w, canvas_h, max_regions=max_regions)

    rects = []
    for c in clusters:
        x1, y1, w, h = c
        rects.append((x1, y1, w, h))

    # Sort rects by height descending
    sorted_rects = sorted(rects, key=lambda r: r[3], reverse=True)

    placed = []
    shelf_x = 0
    shelf_y = 0
    current_shelf_h = 0
    atlas_max_x = 0
    atlas_max_y = 0
    max_shelf_w = canvas_w

    for r in sorted_rects:
        dest_x, dest_y, w, h = r
        if shelf_x + w > max_shelf_w and shelf_x > 0:
            shelf_x = 0
            shelf_y += current_shelf_h
            current_shelf_h = 0

        placed.append((dest_x, dest_y, shelf_x, shelf_y, w, h))
        shelf_x += w
        current_shelf_h = max(current_shelf_h, h)

        atlas_max_x = max(atlas_max_x, shelf_x)
        atlas_max_y = max(atlas_max_y, shelf_y + current_shelf_h)

    if atlas_max_x % 2 != 0: atlas_max_x += 1
    if atlas_max_y % 2 != 0: atlas_max_y += 1

    return atlas_max_x, atlas_max_y, placed

def main():
    with open("def_layout.json", "r", encoding="utf-8") as f:
        normal_layout = json.load(f)

    w, h, placed = compute_shelf_atlas(normal_layout, 3840, 2160, max_regions=3)
    mb = (w * h * 4) / (1024 * 1024)

    print("=================== SHELF PACKING TEST ===================")
    print(f"Atlas Dimensions : {w}x{h} -> {mb:.2f} MB / frame")
    for idx, p in enumerate(placed):
        print(f"  Region {idx+1}: dest=({p[0]},{p[1]}) src=({p[2]},{p[3]}) size={p[4]}x{p[5]}")
    print("==========================================================")

if __name__ == "__main__":
    main()
