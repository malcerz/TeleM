import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.gui.layout_manager import normalize_layout

def compute_clusters(boxes, max_regions=3):
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
    return clusters

def pack_atlas(clusters, canvas_w=1920, canvas_h=1080, padding=4):
    # Try 2 packing layouts:
    # 1. Vertical stack: atlas_w = max(w_i), atlas_h = sum(h_i + pad)
    # 2. Horizontal shelf / multi-shelf: shelf_w <= canvas_w
    # Pick the one with minimal area.
    
    clean_clusters = []
    for c in clusters:
        x1, y1, x2, y2 = c
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(canvas_w, x2)
        y2 = min(canvas_h, y2)
        if x1 % 2 != 0: x1 -= 1
        if y1 % 2 != 0: y1 -= 1
        w = max(2, x2 - x1)
        h = max(2, y2 - y1)
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        clean_clusters.append((x1, y1, w, h))

    # Option A: Vertical stack
    v_max_w = max(c[2] for c in clean_clusters)
    v_regions = []
    cur_y = 0
    for c in clean_clusters:
        x1, y1, w, h = c
        v_regions.append((x1, y1, 0, cur_y, w, h))
        cur_y += h + padding
        if cur_y % 2 != 0: cur_y += 1
    v_atlas_w = v_max_w if v_max_w % 2 == 0 else v_max_w + 1
    v_atlas_h = cur_y
    v_area = v_atlas_w * v_atlas_h

    # Option B: Shelf packing (width up to canvas_w)
    s_regions = []
    shelf_x = 0
    shelf_y = 0
    row_h = 0
    max_x = 0
    for c in clean_clusters:
        x1, y1, w, h = c
        if shelf_x + w > canvas_w and shelf_x > 0:
            shelf_x = 0
            shelf_y += row_h + padding
            if shelf_y % 2 != 0: shelf_y += 1
            row_h = 0
        s_regions.append((x1, y1, shelf_x, shelf_y, w, h))
        shelf_x += w + padding
        if shelf_x % 2 != 0: shelf_x += 1
        row_h = max(row_h, h)
        max_x = max(max_x, shelf_x)
    s_atlas_w = max_x if max_x % 2 == 0 else max_x + 1
    s_atlas_h = shelf_y + row_h
    if s_atlas_h % 2 != 0: s_atlas_h += 1
    s_area = s_atlas_w * s_atlas_h

    if v_area <= s_area:
        return v_atlas_w, v_atlas_h, v_regions, v_area
    else:
        return s_atlas_w, s_atlas_h, s_regions, s_area

layout = normalize_layout("def_layout.json", 1920, 1080)
from scratch.calc_accurate_boxes import boxes

boxes_list = [b["box"] for b in boxes]
for n_reg in (1, 2, 3, 4):
    clusters = compute_clusters(boxes_list, max_regions=n_reg)
    w, h, regs, area = pack_atlas(clusters)
    pct = area / (1920 * 1080) * 100
    mb = (w * h * 4) / (1024 * 1024)
    print(f"\nMax Regions={n_reg}: Atlas {w}x{h} ({mb:.2f} MB/frame, {pct:.1f}% area)")
    for i, r in enumerate(regs):
        print(f"  Reg {i}: src=({r[0]},{r[1]}) size={r[4]}x{r[5]} -> atlas=({r[2]},{r[3]})")
