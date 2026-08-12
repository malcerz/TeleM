"""Test multi-region atlas helper for TeleM layout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Any

def get_layout_hud_regions(layout: dict[str, Any], canvas_w: int = 3840, canvas_h: int = 2160) -> tuple[int, int, list[tuple[int, int, int, int, int, int]]]:
    """Compute compact multi-region atlas bounds for layout.

    Returns:
        atlas_w, atlas_h, regions
        where regions is a list of (dest_x, dest_y, src_x, src_y, region_w, region_h)
    """
    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])
    enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}

    if not enabled_indicators and not custom_texts:
        return 2, 2, [(0, 0, 0, 0, 2, 2)]

    boxes = []
    for key, cfg in enabled_indicators.items():
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
        boxes.append((x1, y1, x2, y2, key))

    for idx, ct_cfg in enumerate(custom_texts):
        lx = ct_cfg.get("x", 0.0)
        ly = ct_cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        x1 = max(0, px - 40)
        y1 = max(0, py - 40)
        x2 = min(canvas_w, px + 500)
        y2 = min(canvas_h, py + 150)
        boxes.append((x1, y1, x2, y2, f"custom_text_{idx}"))

    for b in boxes:
        print(f"Key: {b[4]} | y1={b[1]}, y2={b[3]}, height={b[3]-b[1]}")
    min_y = min(b[1] for b in boxes)
    max_y = max(b[3] for b in boxes)

    # Check if indicators split naturally into Top (y < 45%) and Bottom (y > 45%)
    top_boxes = [b for b in boxes if b[1] < int(canvas_h * 0.45)]
    bot_boxes = [b for b in boxes if b[3] > int(canvas_h * 0.45)]

    # If there are indicators in both top and bottom with a large gap between them (> 250px)
    if top_boxes and bot_boxes:
        top_y1 = min(b[1] for b in top_boxes)
        top_y2 = max(b[3] for b in top_boxes)
        bot_y1 = min(b[1] for b in bot_boxes)
        bot_y2 = max(b[3] for b in bot_boxes)

        gap = bot_y1 - top_y2
        if gap > 250:
            # 2-Region HUD (Top + Bottom)
            top_x1 = min(b[0] for b in top_boxes)
            top_x2 = max(b[2] for b in top_boxes)
            bot_x1 = min(b[0] for b in bot_boxes)
            bot_x2 = max(b[2] for b in bot_boxes)

            w1 = max(2, top_x2 - top_x1)
            h1 = max(2, top_y2 - top_y1)
            w2 = max(2, bot_x2 - bot_x1)
            h2 = max(2, bot_y2 - bot_y1)

            if top_x1 % 2 != 0: top_x1 -= 1
            if top_y1 % 2 != 0: top_y1 -= 1
            if w1 % 2 != 0: w1 += 1
            if h1 % 2 != 0: h1 += 1

            if bot_x1 % 2 != 0: bot_x1 -= 1
            if bot_y1 % 2 != 0: bot_y1 -= 1
            if w2 % 2 != 0: w2 += 1
            if h2 % 2 != 0: h2 += 1

            atlas_w = max(w1, w2)
            atlas_h = h1 + h2

            regions = [
                (top_x1, top_y1, 0, 0, w1, h1),
                (bot_x1, bot_y1, 0, h1, w2, h2)
            ]
            return atlas_w, atlas_h, regions

    # Single region HUD
    min_x = min(b[0] for b in boxes)
    max_x = max(b[2] for b in boxes)
    w = max(2, max_x - min_x)
    h = max(2, max_y - min_y)
    if min_x % 2 != 0: min_x -= 1
    if min_y % 2 != 0: min_y -= 1
    if w % 2 != 0: w += 1
    if h % 2 != 0: h += 1

    return w, h, [(min_x, min_y, 0, 0, w, h)]

def main():
    with open("def_layout.json", "r", encoding="utf-8") as f:
        normal_layout = json.load(f)

    w, h, regions = get_layout_hud_regions(normal_layout, 3840, 2160)
    print("=================== MULTI-REGION ATLAS TEST ===================")
    print(f"Atlas Dimensions: {w}x{h} ({w*h*4 / (1024*1024):.2f} MB per frame)")
    print(f"Region Count    : {len(regions)}")
    for idx, r in enumerate(regions):
        print(f"  Region {idx+1}: dest=({r[0]},{r[1]}) src=({r[2]},{r[3]}) size={r[4]}x{r[5]}")
    print("===============================================================")

if __name__ == "__main__":
    main()
