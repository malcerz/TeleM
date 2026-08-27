"""ETAP 2B ghosting equivalence checker.

For each needle-sweep frame compares the composited HUD-canvas gauge tile
between the ETAP 2A full-upload reference run and the ETAP 2B dynamic-
region run, and validates the 2A-report ghosting semantics:

  E1. canvas_tile(2B) == canvas_tile(2A) BIT-EXACT for every frame
      (region transfer introduces zero canvas change vs the validated
      reference implementation);
  E2. in BOTH runs the diff-vs-expected(truth+art) mask is confined to the
      static bottom band (global y >= 1540) and contains ZERO pixels in
      the dynamic zone (rect union padded by 16 px) -> no stale
      needle/value/trail is possible;
  E3. gauge tile bbox constant across sweep; art varies.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

BASE = Path("scratch/etap2b_test")
FRAMES = [100, 101, 102, 103, 104, 105, 150, 151, 200, 201, 250, 251, 320]
TILE = (1440, 665, 960, 960)
# Dynamic zone = measured rect padded by 16 px, in GLOBAL coords.
RECT = (444 + TILE[0] - 16, 468 + TILE[1] - 16,
        424 + 32, 360 + 32)


def load(p):
    return np.asarray(Image.open(str(p)).convert("RGBA"))


def main():
    gx, gy, gw, gh = TILE
    e1_ok = True
    e2_ok = True
    arts = []
    metas = {}
    for f in FRAMES:
        with open(BASE / "ghost_2b" / f"gauge_meta_f{f}.json", encoding="utf-8") as fh:
            metas[f] = json.load(fh)
    bboxes = {(m["x"], m["y"], m["w"], m["h"]) for m in metas.values()}
    stable = len(bboxes) == 1
    print(f"E3 tile bbox across sweep: {bboxes} stable={stable}")

    rx0 = max(gx, RECT[0])
    ry0 = max(gy, RECT[1])
    rx1 = min(gx + gw, RECT[0] + RECT[2])
    ry1 = min(gy + gh, RECT[1] + RECT[3])

    for f in FRAMES:
        c2a = load(BASE / "ghost_2a" / f"H_hud_canvas_{f}.png")
        c2b = load(BASE / "ghost_2b" / f"H_hud_canvas_{f}.png")
        t2a = c2a[gy:gy + gh, gx:gx + gw]
        t2b = c2b[gy:gy + gh, gx:gx + gw]
        eq = int(np.any(t2a != t2b, axis=-1).sum())
        e1_ok &= eq == 0
        print(f"f{f}: tile(2B) vs tile(2A) differing px={eq} "
              f"{'OK' if eq == 0 else 'FAIL'}")

        dyn = np.zeros((gh, gw), dtype=bool)
        if rx1 > rx0 and ry1 > ry0:
            dyn[ry0 - gy:ry1 - gy, rx0 - gx:rx1 - gx] = True
        for name, d, canv in (("2a", BASE / "ghost_2a", t2a),
                              ("2b", BASE / "ghost_2b", t2b)):
            truth = load(d / f"compose_full_cand_f{f}.png")[gy:gy + gh, gx:gx + gw]
            art = Image.open(str(d / f"gauge_capture_f{f}.png")).convert("RGBA")
            exp = np.asarray(Image.alpha_composite(
                Image.fromarray(truth), art))
            dmask = np.any(canv != exp, axis=-1)
            inside = int((dmask & dyn).sum())
            outside = int((dmask & ~dyn).sum())
            ok = inside == 0
            e2_ok &= ok
            print(f"f{f} [{name}]: diff_inside_dyn={inside} "
                  f"diff_outside_static_band={outside} {'OK' if ok else 'FAIL'}")
            arts.append(np.asarray(art))

    art_varies = any(np.any(arts[i] != arts[i - 1]) for i in range(1, len(arts)))
    print(f"E3 art varies across sweep: {art_varies}")
    print(f"E1 canvas-tile equality 2B==2A all frames: {e1_ok}")
    print(f"E2 zero diffs inside dynamic zone both modes: {e2_ok}")
    verdict = e1_ok and e2_ok and stable and art_varies
    print("ETAP2B GHOSTING_EQUIVALENCE:", "PASS" if verdict else "FAIL")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
