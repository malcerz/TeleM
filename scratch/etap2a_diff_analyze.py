"""ETAP 2A diff analyzer: locate WHERE and HOW ref/cand HUD dumps differ."""
import numpy as np
from PIL import Image
from pathlib import Path

OUT = Path("scratch/etap2a_test")
GAUGE = (1440, 665, 960, 960)
CADENCE = (456, 1538, 1160, 466)


def load(frame):
    a = np.array(Image.open(OUT / f"ref_short_H_hud_canvas_{frame}.png").convert("RGBA"))
    b = np.array(Image.open(OUT / f"cand_short_H_hud_canvas_{frame}.png").convert("RGBA"))
    return a, b


def analyze(a, b, frame):
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    diff = np.any(d > 0, axis=-1)
    ys, xs = np.nonzero(diff)
    print(f"=== frame {frame} ===")
    print(f"diff pixels: {len(xs)}")
    if len(xs):
        print(f"diff bbox: x[{xs.min()}..{xs.max()}] y[{ys.min()}..{ys.max()}]")
        # per-channel counts
        for c, name in enumerate("RGBA"):
            ch = d[..., c]
            n = int((ch > 0).sum())
            if n:
                print(f"  channel {name}: {n} px changed, max={int(ch.max())}, "
                      f"mean_on_changed={float(ch[ch > 0].mean()):.2f}")
        # how many diff pixels are alpha-only?
        rgb = d[..., :3]
        alpha_only = int(((rgb.sum(axis=-1) == 0) & (d[..., 3] > 0)).sum())
        print(f"  alpha-only diffs: {alpha_only}")
        # histogram of max per-pixel diff
        mx = d.max(axis=-1)
        for lo, hi in ((1, 8), (9, 32), (33, 128), (129, 255)):
            print(f"  max-diff in ({lo},{hi}): {int(((mx >= lo) & (mx <= hi)).sum())}")
        # overlap zone cadence ROI
        cx0, cy0, cw, chh = CADENCE
        in_cad = diff[cy0:cy0 + chh, cx0:cx0 + cw]
        if in_cad.any():
            cy, cx = np.nonzero(in_cad)
            print(f"  diffs inside CADENCE ROI: {len(cx)} at abs x[{cx.min()+cx0}..{cx.max()+cx0}] y[{cy.min()+cy0}..{cy.max()+cy0}]")
        # save visualizations
        gx, gy, gw, gh = GAUGE
        crop_ref = a[gy:gy+gh, gx:gx+gw]
        crop_can = b[gy:gy+gh, gx:gx+gw]
        Image.fromarray(crop_ref).save(OUT / f"an_f{frame}_gauge_ref.png")
        Image.fromarray(crop_can).save(OUT / f"an_f{frame}_gauge_cand.png")
        heat = np.zeros((gh, gw, 3), dtype=np.uint8)
        sub = mx[gy:gy+gh, gx:gx+gw]
        heat[..., 0] = np.clip(sub * 4, 0, 255)
        heat[..., 1] = np.where(sub > 128, 255, 0)
        Image.fromarray(heat).save(OUT / f"an_f{frame}_gauge_diffheat.png")


for f in (30, 300):
    a, b = load(f)
    analyze(a, b, f)
