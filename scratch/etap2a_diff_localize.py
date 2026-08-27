"""Three-way zone table: ref-vs-truth / cand-vs-truth / ref-vs-cand.

Classifies every HUD-canvas deviation for the ETAP 2A report:
  wipe-class   : truth has content, one canvas lost it (clear-after-upload
                 defect or gauge-tile clear) -> cand must be clean here
  fringe-class : shared AA/alpha-conversion artifact of the ABOVE upload
                 pipeline, identical in both runs, pre-existing
"""
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path("scratch/etap2a_test")
FRAMES = (30, 300)
GAUGE_TILE = (1440, 665, 960, 960)

ZONES = {
    # original victim ROI: ruler track + tick under the gauge tile
    "DIST_ROI": (1445, 1575, 299, 47),
    # full dist_visual widget bbox outside the gauge tile (strip zone)
    "DIST_OUTSIDE_TILE": (1373, 1549, 1095, 98),
    # control: above-text zone far from gauge/charts
    "CONTROL_TEXT": (152, 162, 800, 400),
}


def load(name):
    return np.asarray(Image.open(str(OUT / name)).convert("RGBA"))


def box_of(canvas, box):
    bx, by, bw, bh = box
    return canvas[by:by + bh, bx:bx + bw]


grand_ok = True
for f in FRAMES:
    ref_c = load(f"ref_short_H_hud_canvas_{f}.png")
    cand_c = load(f"cand_short_H_hud_canvas_{f}.png")
    truth = load(f"compose_full_cand_f{f}.png")  # deterministic == ref truth
    print(f"===== frame {f} =====")
    for name, box in ZONES.items():
        r = box_of(ref_c, box)
        c = box_of(cand_c, box)
        t = box_of(truth, box)
        rt = int(np.any(r != t, axis=-1).sum())
        ct = int(np.any(c != t, axis=-1).sum())
        rc = int(np.any(r != c, axis=-1).sum())
        # wipe-class within this zone: truth non-transparent, canvas transparent
        t_has = np.any(t != 0, axis=-1)
        r_wipe = int((t_has & np.all(r == 0, axis=-1)).sum())
        c_wipe = int((t_has & np.all(c == 0, axis=-1)).sum())
        print(f"{name:18s} ref~truth={rt:6d} cand~truth={ct:6d} "
              f"ref~cand={rc:6d} | wiped_px ref={r_wipe:5d} cand={c_wipe:5d}")

# tile-interior below-widget sanity for cand (gauge art excluded by design)
gx, gy, gw, gh = GAUGE_TILE
print(f"note: gauge tile interior is GPU-blend territory "
      f"({gw * gh} px), excluded from truth gates")

# Locate the residual cand wiped pixels inside DIST_OUTSIDE_TILE
bx, by, bw, bh = ZONES["DIST_OUTSIDE_TILE"]
t = box_of(truth, bx, by, bw, bh) if False else truth[by:by + bh, bx:bx + bw]
c = cand_c[by:by + bh, bx:bx + bw]
t_has = np.any(t != 0, axis=-1)
c_zero = np.all(c == 0, axis=-1)
ys, xs = np.where(t_has & c_zero)
print(f"cand residual wiped px in DIST_OUTSIDE_TILE: {len(ys)}")
if len(ys):
    print(f"  bbox x[{xs.min() + bx}..{xs.max() + bx}] "
          f"y[{ys.min() + by}..{ys.max() + by}]")
    for i in range(min(len(ys), 10)):
        y, x = ys[i] + by, xs[i] + bx
        print(f"  ({x},{y}) truth={tuple(int(v) for v in truth[y, x])}")
    # relation to chart boxes
    for nm, cbx, cby, cbw, cbh in (
        ("CADENCE", 456, 1538, 1160, 466), ("HR", 2223, 1538, 1160, 466),
        ("GAUGE_TILE", gx, gy, gw, gh),
    ):
        inside = int(np.sum((xs + bx >= cbx) & (xs + bx < cbx + cbw) &
                            (ys + by >= cby) & (ys + by < cby + cbh)))
        print(f"  inside {nm}: {inside}")

