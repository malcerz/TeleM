"""ETAP 2C ghosting/parity equivalence checker (FULL vs AUTO runs).

  G1. canvas gauge tile bit-exact between FULL-TILE and AUTO runs on every
      sweep frame (region transfer introduces zero canvas change vs the
      validated reference implementation);
  G2. AUTO run oracle: missed_dynamic_pixels == 0 (from profile JSON);
  G3. gauge tile bbox stable across sweep; capture art varies.

Tile bbox is read from the probe gauge_meta JSONs — no hardcoded rects.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

BASE = Path("scratch/etap2c_test")
FRAMES = [100, 101, 102, 103, 104, 105, 150, 151, 200, 201, 250, 251, 320]


def load(p):
    return np.asarray(Image.open(str(p)).convert("RGBA"))


def main():
    metas = {}
    for f in FRAMES:
        with open(BASE / "ghost_auto" / f"gauge_meta_f{f}.json",
                  encoding="utf-8") as fh:
            metas[f] = json.load(fh)
    bboxes = {(m["x"], m["y"], m["w"], m["h"]) for m in metas.values()}
    stable = len(bboxes) == 1
    gx, gy, gw, gh = next(iter(bboxes))
    print(f"G3 tile bbox across sweep: {bboxes} stable={stable}")

    e1_ok = True
    arts = []
    for f in FRAMES:
        c_full = load(BASE / "ghost_full" / f"H_hud_canvas_{f}.png")
        c_auto = load(BASE / "ghost_auto" / f"H_hud_canvas_{f}.png")
        t_full = c_full[gy:gy + gh, gx:gx + gw]
        t_auto = c_auto[gy:gy + gh, gx:gx + gw]
        eq = int(np.any(t_full != t_auto, axis=-1).sum())
        e1_ok &= eq == 0
        print(f"f{f}: tile(AUTO) vs tile(FULL) differing px={eq} "
              f"{'OK' if eq == 0 else 'FAIL'}")
        arts.append(np.asarray(Image.open(
            str(BASE / "ghost_auto" / f"gauge_capture_f{f}.png")
        ).convert("RGBA")))

    art_varies = any(np.any(arts[i] != arts[i - 1]) for i in range(1, len(arts)))
    prof = json.loads((BASE / "ghost_auto" / "ghost.mp4.amd_profile.json")
                      .read_text(encoding="utf-8"))
    e2c = prof.get("etap2c_gauge_regions", {})
    missed = e2c.get("missed_dynamic_pixels", -1)
    oframes = e2c.get("oracle_frames", 0)
    g2_ok = (oframes > 0 and missed == 0
             and e2c.get("mode") == "AUTO")
    print(f"AUTO oracle: frames={oframes} "
          f"region_frames={e2c.get('oracle_region_frames')} "
          f"full_frames={e2c.get('oracle_full_frames')} "
          f"changed={e2c.get('oracle_changed_pixels')} missed={missed}")
    print(f"G2 AUTO oracle missed==0: {g2_ok}")
    print(f"G3 art varies across sweep: {art_varies}")
    print(f"G1 canvas-tile equality AUTO==FULL all frames: {e1_ok}")
    verdict = e1_ok and g2_ok and stable and art_varies
    print("ETAP2C GHOSTING_PARITY:", "PASS" if verdict else "FAIL")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
