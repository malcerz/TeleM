import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from typing import Any
import itertools
import numpy as np
from PIL import Image
from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay

def get_layout_hud_regions_v3(
    layout: dict[str, Any], canvas_w: int, canvas_h: int, max_regions: int = 3, padding: int = 4
) -> tuple[int, int, list[tuple[int, int, int, int, int, int]]]:
    """Compute compact multi-region atlas bounds for layout with exact center/top-left geometry."""
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
            x1, y1 = px - radius - 10, py - radius - 10
            x2, y2 = px + radius + 10, py + radius + 10
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
            sz = cfg.get("size", cfg.get("w", 0.3))
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            cw = size_px + 60
            ch = max(50, int(size_px * 0.45)) + 50
            x1 = px - cw // 2 - 20
            y1 = py - ch // 2 - 20
            x2 = px + cw // 2 + 20
            y2 = py + ch // 2 + 20
        elif key in ("time_block", "time_display") or "time" in key:
            x1 = px - 20
            y1 = py - 20
            x2 = px + int(canvas_w * 0.20) + 20
            y2 = py + int(canvas_h * 0.12) + 20
        else:
            # text indicator
            fs_val = cfg.get("font_size", cfg.get("size", 0.02))
            fs = max(10, int(round(fs_val * min_dim)) if fs_val <= 1.0 else int(round((fs_val / 100.0) * min_dim)))
            text_w = max(int(canvas_w * 0.12), fs * 12)
            text_h = max(int(canvas_h * 0.06), fs * 3 + 20)
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

img = compose_overlay(
    1920, 1080, layout, "",
    "2026-08-20", "12:34:56",
    28.5, 4500.0, 12000.0,
    145.0, 50.0, 300.0,
    100.0, 500.0, 25.0,
    indicator_values={
        "fit_cadence_text": 85.0,
        "fit_enhanced_speed_text": 28.5,
        "fit_heart_rate_text": 142.0,
        "fit_temperature_text": 24.5,
        "iso_text": 100.0,
        "exposure_text": 500.0,
        "temp_text": 25.0,
        "fit_battery_text": 85.0,
        "fit_battery_pct_text": 85.0,
        "fit_solar_pct_text": 45.0,
    },
    chart_data={"cadence": [(i, 70 + i%30) for i in range(100)], "heart_rate": [(i, 130 + i%20) for i in range(100)]},
    gps_track=[(52.0 + i*0.001, 21.0 + i*0.001) for i in range(100)],
    current_position=0.5,
)

arr_full = np.asarray(img)
alpha_full = arr_full[..., 3]
aw, ah, regs = get_layout_hud_regions_v3(layout, 1920, 1080, max_regions=3)

print(f"HUD Atlas: {aw}x{ah} ({(aw*ah*4)/(1024*1024):.2f} MB, {(aw*ah)/(1920*1080)*100:.1f}% area)")
print(f"Regions: {len(regs)}")
for i, r in enumerate(regs):
    print(f"  Reg {i}: dest=({r[0]},{r[1]}) size=({r[4]}x{r[5]}) -> atlas=({r[2]},{r[3]})")

reconstructed = np.zeros((1080, 1920, 4), dtype=np.uint8)
atlas_img = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
for r in regs:
    dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
    crop = img.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
    atlas_img.paste(crop, (atlas_x, atlas_y))

for r in regs:
    dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
    crop_from_atlas = atlas_img.crop((atlas_x, atlas_y, atlas_x + rw, atlas_y + rh))
    reconstructed[dest_y:dest_y+rh, dest_x:dest_x+rw] = np.asarray(crop_from_atlas)

diff = np.abs(arr_full.astype(int) - reconstructed.astype(int))
max_diff = int(np.max(diff))
diff_px = int(np.count_nonzero(diff.any(axis=-1)))
total_alpha_px = int(np.count_nonzero(alpha_full > 0))

lost_alpha_mask = (alpha_full > 0) & (reconstructed[..., 3] == 0)
lost_count = int(np.count_nonzero(lost_alpha_mask))

print(f"Max diff: {max_diff}")
print(f"Different pixels: {diff_px}")
print(f"Lost alpha pixels outside regions: {lost_count}")
if max_diff == 0 and diff_px == 0:
    print("STATUS: 100% BIT-EXACT ZERO LOSS ZERO CLIPPING!")
