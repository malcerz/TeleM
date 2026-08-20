import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

def pack_atlas_optimal(clusters, canvas_w=1920, canvas_h=1080, padding=4):
    clean = []
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
        clean.append((x1, y1, w, h))

    best_area = float("inf")
    best_res = None

    import itertools
    for order in itertools.permutations(clean):
        # Shelf packing with max width = canvas_w
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
            best_res = (aw, ah, regions, area)

    return best_res

from scratch.calc_accurate_boxes import boxes
from scratch.test_cluster_packing import compute_clusters

boxes_list = [b["box"] for b in boxes]
for n_reg in (1, 2, 3, 4):
    clusters = compute_clusters(boxes_list, max_regions=n_reg)
    w, h, regs, area = pack_atlas_optimal(clusters)
    pct = area / (1920 * 1080) * 100
    mb = (w * h * 4) / (1024 * 1024)
    print(f"\nMax Regions={n_reg}: Atlas {w}x{h} ({mb:.2f} MB/frame, {pct:.1f}% area)")
    for i, r in enumerate(regs):
        print(f"  Reg {i}: src=({r[0]},{r[1]}) size={r[4]}x{r[5]} -> atlas=({r[2]},{r[3]})")
