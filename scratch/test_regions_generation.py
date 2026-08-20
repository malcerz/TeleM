import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from typing import Any
import itertools
from src.gui.layout_manager import normalize_layout

def get_layout_hud_regions_v2(
    layout: dict[str, Any], canvas_w: int, canvas_h: int, max_regions: int = 3, padding: int = 4
) -> tuple[int, int, list[tuple[int, int, int, int, int, int]]]:
    """Compute compact multi-region atlas bounds for layout.

    Returns:
        atlas_w, atlas_h, regions
        where regions is a list of (dest_x, dest_y, atlas_x, atlas_y, region_w, region_h)
    """
    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])
    enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}

    if not enabled_indicators and not custom_texts:
        return 2, 2, [(0, 0, 0, 0, 2, 2)]

    min_dim = min(canvas_w, canvas_h)
    boxes = []

    for key, cfg in enabled_indicators.items():
        lx = cfg.get("x", 0.0)
        ly = cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        rot = int(cfg.get("rotation", 0)) % 360

        form = cfg.get("form", "text")
        if form == "gauge":
            sz = cfg.get("size", 0.1)
            size_px = int(round(sz * min_dim)) if sz <= 1.0 else int(round((sz / 100.0) * min_dim))
            radius = int(size_px * 1.35)
            x1, y1 = px - radius, py - radius
            x2, y2 = px + radius, py + radius
        elif form in ("bar", "segment_bar"):
            sz = cfg.get("size", 0.2)
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            bar_w = size_px + 80
            bar_h = max(60, int(size_px * 0.35)) + 50
            if rot in (90, 270):
                w_bar, h_bar = bar_h, bar_w
            else:
                w_bar, h_bar = bar_w, bar_h
            x1 = px - w_bar // 2 - 20
            y1 = py - h_bar // 2 - 20
            x2 = px + w_bar // 2 + 20
            y2 = py + h_bar // 2 + 20
        elif form in ("chart", "moving_map", "static_map", "map"):
            cw = cfg.get("w", 0.35)
            ch = cfg.get("h", 0.25)
            w_px = int(round(cw * canvas_w)) if cw <= 1.0 else int(round((cw / 100.0) * canvas_w))
            h_px = int(round(ch * canvas_h)) if ch <= 1.0 else int(round((ch / 100.0) * canvas_h))
            w_px = max(w_px, int(canvas_w * 0.25))
            h_px = max(h_px, int(canvas_h * 0.20))
            x1, y1 = px - 20, py - 20
            x2, y2 = px + w_px + 30, py + h_px + 30
        elif key in ("time_block", "time_display") or "time" in key:
            x1, y1 = px - 20, py - 20
            x2, y2 = px + int(canvas_w * 0.18) + 20, py + int(canvas_h * 0.10) + 20
        else:
            # text indicator
            fs_val = cfg.get("font_size", cfg.get("size", 0.02))
            fs = max(10, int(round(fs_val * min_dim)) if fs_val <= 1.0 else int(round((fs_val / 100.0) * min_dim)))
            text_w = max(int(canvas_w * 0.10), fs * 10)
            text_h = max(int(canvas_h * 0.05), fs * 2 + 20)
            x1 = px - 20
            y1 = py - 20
            x2 = px + text_w + 20
            y2 = py + text_h + 20

        boxes.append([max(0, x1), max(0, y1), min(canvas_w, x2), min(canvas_h, y2)])

    for ct_cfg in custom_texts:
        if not ct_cfg.get("enabled", True):
            continue
        lx = ct_cfg.get("x", 0.0)
        ly = ct_cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        boxes.append([max(0, px - 20), max(0, py - 20), min(canvas_w, px + int(canvas_w * 0.30) + 20), min(canvas_h, py + int(canvas_h * 0.10) + 20)])

    if not boxes:
        return 2, 2, [(0, 0, 0, 0, 2, 2)]

    # Hierarchical clustering to at most max_regions
    clusters = [[b[0], b[1], b[2], b[3]] for b in boxes]
    while len(clusters) > max_regions:
        best_pair = None
        best_waste = float("inf")
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                b1, b2 = clusters[i], clusters[j]
                mb = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
                ma = (mb[2] - mb[0]) * (mb[3] - mb[1])
                a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
                a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
                waste = ma - (a1 + a2)
                if waste < best_waste:
                    best_waste = waste
                    best_pair = (i, j)

        if best_pair is None:
            break
        i, j = best_pair
        b1, b2 = clusters[i], clusters[j]
        mb = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
        clusters.pop(j)
        clusters.pop(i)
        clusters.append(mb)

    # Format even dimensions
    clean_clusters = []
    for c in clusters:
        x1, y1, x2, y2 = c
        if x1 % 2 != 0: x1 -= 1
        if y1 % 2 != 0: y1 -= 1
        w = max(2, x2 - x1)
        h = max(2, y2 - y1)
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        w = min(canvas_w - x1, w)
        h = min(canvas_h - y1, h)
        clean_clusters.append((x1, y1, w, h))

    # Optimal shelf packing over all cluster permutations
    best_area = float("inf")
    best_res = None

    for order in itertools.permutations(clean_clusters):
        shelf_x = 0
        shelf_y = 0
        row_h = 0
        max_x = 0
        regions = []
        for c in order:
            x1, y1, w, h = c
            if shelf_x + w > canvas_w and shelf_x > 0:
                shelf_x = 0
                shelf_y += row_h + padding
                if shelf_y % 2 != 0: shelf_y += 1
                row_h = 0
            regions.append((x1, y1, shelf_x, shelf_y, w, h))
            shelf_x += w + padding
            if shelf_x % 2 != 0: shelf_x += 1
            row_h = max(row_h, h)
            max_x = max(max_x, shelf_x)
        aw = max_x if max_x % 2 == 0 else max_x + 1
        ah = shelf_y + row_h
        if ah % 2 != 0: ah += 1
        area = aw * ah
        if area < best_area:
            best_area = area
            best_res = (aw, ah, regions)

    return best_res

layout = normalize_layout("def_layout.json", 1920, 1080)
aw, ah, regs = get_layout_hud_regions_v2(layout, 1920, 1080, max_regions=3)
area = aw * ah
pct = area / (1920 * 1080) * 100
mb = (aw * ah * 4) / (1024 * 1024)
print(f"HUD Atlas for def_layout.json: {aw}x{ah} ({mb:.2f} MB, {pct:.1f}% area)")
print(f"Number of regions: {len(regs)}")
for i, r in enumerate(regs):
    print(f"  Region {i}: dest=({r[0]},{r[1]}) size={r[4]}x{r[5]} -> atlas=({r[2]},{r[3]})")
