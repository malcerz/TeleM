"""ETAP 2A parity gate (final semantics).

Dumps come from DumpRGBATextureToFile(m_hudTexture) at frames 30/300 (the
composited RGBA canvas BEFORE NV12 conversion / AMF encode) and from
composed_img (Pillow compose ground truth) via AMD_ETAP2A_COMPOSE_PROBE.

Established facts (see RAPORT_AMD_ETAP_2A_AFTER_MAP_GAUGE_GPU.md):
  * compose is deterministic and byte-identical between ref/cand runs;
  * the gauge tile interior is GPU-blend territory (compose omits the
    captured gauge by design);
  * REF carries a PRE-EXISTING wipe defect: legacy ordering erases previous
    ABOVE/chart regions AFTER the below-widget uploads, destroying restored
    below content under those regions (dist_visual ruler band). CAND (early
    clear + force-dirty) restores it;
  * a shared, static AA-stroke artifact family (above-canvas uploads)
    exists identically in both runs and cancels in ref-vs-cand.

Gates
-----
GATE_VICTIM_ROI      : original failing ROI must be zero in ref~cand AND
                       cand~truth (the actual ETAP 2A acceptance).
GATE_NO_NEW_WIPES    : cand transparent-where-truth-has-content count in the
                       dist zone must be <1% of the same count for REF.
GATE_CONTROL_UNTOUCHED: control zone (no gauge interaction) ref~cand == 0.
GATE_TRUTH_DETERMINISM: ref/cand compose dumps identical.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path("scratch/etap2a_test")
FRAMES = (30, 300)
DIST_ROI = (1445, 1575, 299, 47)          # original victim ROI
DIST_ZONE = (1373, 1549, 1095, 98)        # full dist_visual widget bbox
CONTROL = (152, 162, 800, 400)            # above-text control zone
LEGACY_ROIS = {
    "FULL": None,
    "GAUGE": (1440, 665, 960, 960),
    "MAP": (2880, 260, 691, 691),
    "CADENCE": (456, 1538, 1160, 466),
    "HR": (2223, 1538, 1160, 466),
    "DIST_VISUAL": DIST_ROI,
}


def load(name):
    return np.asarray(Image.open(str(OUT / name)).convert("RGBA"))


def box_of(a, box):
    bx, by, bw, bh = box
    return a[by:by + bh, bx:bx + bw]


def diff_count(a, b):
    return int(np.any(a != b, axis=-1).sum())


def wiped_count(truth_box, canvas_box):
    t_has = np.any(truth_box != 0, axis=-1)
    c_zero = np.all(canvas_box == 0, axis=-1)
    return int((t_has & c_zero).sum())


def main():
    results = []

    # GATE_TRUTH_DETERMINISM ----------------------------------------------
    g4 = all(diff_count(load(f"compose_full_ref_f{f}.png"),
                        load(f"compose_full_cand_f{f}.png")) == 0
             for f in FRAMES)
    print(f"GATE_TRUTH_DETERMINISM: {'PASS' if g4 else 'FAIL'}")
    results.append(g4)

    # GATE_VICTIM_ROI -------------------------------------------------------
    g1 = True
    for f in FRAMES:
        r = box_of(load(f"ref_short_H_hud_canvas_{f}.png"), DIST_ROI)
        c = box_of(load(f"cand_short_H_hud_canvas_{f}.png"), DIST_ROI)
        t = box_of(load(f"compose_full_cand_f{f}.png"), DIST_ROI)
        rc, ct = diff_count(r, c), diff_count(c, t)
        print(f"GATE_VICTIM_ROI f{f}: ref~cand={rc} cand~truth={ct}")
        g1 &= rc == 0 and ct == 0
    print(f"GATE_VICTIM_ROI: {'PASS' if g1 else 'FAIL'}")
    results.append(g1)

    # GATE_NO_NEW_WIPES -----------------------------------------------------
    g2 = True
    for f in FRAMES:
        t = box_of(load(f"compose_full_cand_f{f}.png"), DIST_ZONE)
        rw = wiped_count(t, box_of(load(f"ref_short_H_hud_canvas_{f}.png"), DIST_ZONE))
        cw = wiped_count(t, box_of(load(f"cand_short_H_hud_canvas_{f}.png"), DIST_ZONE))
        ok = cw * 100 < rw  # strictly below 1% of REF wipes
        print(f"GATE_NO_NEW_WIPES f{f}: ref_wiped={rw} cand_wiped={cw} "
              f"{'PASS' if ok else 'FAIL'}")
        g2 &= ok
    results.append(g2)

    # GATE_CONTROL_UNTOUCHED ------------------------------------------------
    g3 = all(diff_count(box_of(load(f"ref_short_H_hud_canvas_{f}.png"), CONTROL),
                        box_of(load(f"cand_short_H_hud_canvas_{f}.png"), CONTROL)) == 0
             for f in FRAMES)
    print(f"GATE_CONTROL_UNTOUCHED: {'PASS' if g3 else 'FAIL'}")
    results.append(g3)

    # Legacy ROI table (informational continuity) ---------------------------
    for f in FRAMES:
        a = load(f"ref_short_H_hud_canvas_{f}.png")
        b = load(f"cand_short_H_hud_canvas_{f}.png")
        parts = []
        for n, bx in LEGACY_ROIS.items():
            av = a if bx is None else box_of(a, bx)
            bv = b if bx is None else box_of(b, bx)
            parts.append(f"{n}={diff_count(av, bv)}")
        print(f"ROI_TABLE f{f}: " + " ".join(parts))

    ok = all(results)
    print("PARITY_GATE:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
