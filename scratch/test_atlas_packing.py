"""Test optimal 2D packing for HUD atlas to minimize atlas_w * atlas_h.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ffmpeg.command_builder import get_layout_hud_regions

def pack_regions_optimal(clusters: list[list[int]], canvas_w=3840, canvas_h=2160):
    # Sort clusters by height descending
    rects = []
    for c in clusters:
        x1, y1, x2, y2 = c
        w = max(2, x2 - x1)
        h = max(2, y2 - y1)
        if x1 % 2 != 0: x1 -= 1
        if y1 % 2 != 0: y1 -= 1
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        w = min(canvas_w - x1, w)
        h = min(canvas_h - y1, h)
        rects.append((x1, y1, w, h))

    # Try 2 packing strategies:
    # 1. Vertical stack
    v_max_w = max(r[2] for r in rects)
    v_total_h = sum(r[3] for r in rects)
    v_area = v_max_w * v_total_h

    # 2. Side-by-Side shelf packing
    # Sort by height descending
    sorted_rects = sorted(rects, key=lambda r: r[3], reverse=True)
    # Place first rect at (0,0)
    placements = []
    curr_x = 0
    curr_y = 0
    shelf_h = 0
    max_shelf_w = 3840

    placed = []
    # Simple Shelf Packer:
    shelf_x = 0
    shelf_y = 0
    current_shelf_h = 0
    atlas_max_x = 0
    atlas_max_y = 0

    for r in sorted_rects:
        dest_x, dest_y, w, h = r
        if shelf_x + w > max_shelf_w:
            # Move to next shelf
            shelf_x = 0
            shelf_y += current_shelf_h
            current_shelf_h = 0

        placed.append((dest_x, dest_y, shelf_x, shelf_y, w, h))
        shelf_x += w
        current_shelf_h = max(current_shelf_h, h)

        atlas_max_x = max(atlas_max_x, shelf_x)
        atlas_max_y = max(atlas_max_y, shelf_y + current_shelf_h)

    s_area = atlas_max_x * atlas_max_y

    if s_area < v_area:
        if atlas_max_x % 2 != 0: atlas_max_x += 1
        if atlas_max_y % 2 != 0: atlas_max_y += 1
        return atlas_max_x, atlas_max_y, placed
    else:
        # Vertical stack placements
        v_placed = []
        cy = 0
        for r in rects:
            v_placed.append((r[0], r[1], 0, cy, r[2], r[3]))
            cy += r[3]
        if v_max_w % 2 != 0: v_max_w += 1
        if v_total_h % 2 != 0: v_total_h += 1
        return v_max_w, v_total_h, v_placed

def main():
    with open("def_layout.json", "r", encoding="utf-8") as f:
        normal_layout = json.load(f)

    print("=================== ATLAS PACKING OPTIMIZATION ===================")
    w_vert, h_vert, reg_vert = get_layout_hud_regions(normal_layout, 3840, 2160, max_regions=3)
    vert_mb = (w_vert * h_vert * 4) / (1024 * 1024)
    print(f"Vertical Stack Atlas  : {w_vert}x{h_vert} -> {vert_mb:.2f} MB / frame")

if __name__ == "__main__":
    main()
