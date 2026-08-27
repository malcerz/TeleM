"""ETAP 2A ghosting / AFTER-MAP tile parity across a needle-sweep dump set.

For every dumped frame f:
  expected_tile(f) = PIL alpha_composite(compose_truth.crop(tile), gauge_capture)
  PASS requires canvas.crop(tile) == expected_tile(f) BYTE-EXACT.

Because the whole previous gauge tile is erased every frame before any
redraw, any stale needle / value / trail from earlier frames would appear as
canvas pixels not explained by (current truth + current gauge art) and break
the exact comparison.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path("scratch/etap2a_test")
FRAMES = [100, 101, 102, 103, 104, 105, 150, 151, 200, 201, 250, 251, 320]


def load_canvas(f):
    # Native dumps land in the process CWD (repo root) without a tag prefix.
    return np.asarray(Image.open(f"H_hud_canvas_{f}.png").convert("RGBA"))


def load(name):
    return np.asarray(Image.open(str(OUT / name)).convert("RGBA"))


def main():
    metas = {}
    for f in FRAMES:
        with open(OUT / f"gauge_meta_f{f}.json", encoding="utf-8") as fh:
            metas[f] = json.load(fh)
    xs = {m["x"] for m in metas.values()}
    ys = {m["y"] for m in metas.values()}
    ws = {m["w"] for m in metas.values()}
    hs = {m["h"] for m in metas.values()}
    print(f"tile bbox across sweep: x={xs} y={ys} w={ws} h={hs}")
    stable = len(xs) == len(ys) == len(ws) == len(hs) == 1

    all_ok = True
    art_varies = False
    prev_art = None
    for f in FRAMES:
        m = metas[f]
        gx, gy, gw, gh = m["x"], m["y"], m["w"], m["h"]
        canvas = load_canvas(f)[gy:gy + gh, gx:gx + gw]
        truth = load(f"compose_full_cand_f{f}.png")[gy:gy + gh, gx:gx + gw]
        gauge_img = Image.open(str(OUT / f"gauge_capture_f{f}.png")).convert("RGBA")
        if gauge_img.size != (gw, gh):
            print(f"f{f}: SIZE MISMATCH gauge={gauge_img.size} tile={(gw, gh)}")
            all_ok = False
            continue
        expected = Image.alpha_composite(
            Image.fromarray(truth), gauge_img)
        exp = np.asarray(expected)
        d = np.any(canvas != exp, axis=-1)
        n = int(d.sum())
        maxd = int(np.abs(canvas.astype(int) - exp.astype(int)).max()) if n else 0
        art = np.asarray(gauge_img)
        if prev_art is not None and np.any(np.any(art != prev_art, axis=-1)):
            art_varies = True
        prev_art = art
        status = "OK" if n == 0 else "DIFF"
        if n != 0:
            all_ok = False
        print(f"f{f}: tile_diff_px={n:7d} max_delta={maxd:3d} {status}")

    # Static-shared classification: the ~1606-px stroke set must be
    #  (1) the SAME mask in every sweep frame,
    #  (2) carry CONSTANT canvas values in every frame, and
    #  (3) be accompanied by nothing else — outside the set every tile pixel
    #      equals expected(truth+gauge) per frame, so any stale needle /
    #      value / trail from an earlier frame would necessarily break (1)/(2)
    #      or appear outside the set.  Also spot-checks that the same strokes
    #      exist identically in the REF canvas (pre-existing, shared class).
    diff_masks = []
    for f in FRAMES:
        m = metas[f]
        gx, gy, gw, gh = m["x"], m["y"], m["w"], m["h"]
        c = load_canvas(f)[gy:gy + gh, gx:gx + gw]
        t = load(f"compose_full_cand_f{f}.png")[gy:gy + gh, gx:gx + gw]
        g = Image.open(str(OUT / f"gauge_capture_f{f}.png")).convert("RGBA")
        e = np.asarray(Image.alpha_composite(Image.fromarray(t), g))
        diff_masks.append((np.any(c != e, axis=-1), c, e))
    base_mask, base_canvas_t, _ = diff_masks[0]
    mask_const = True
    values_const = True
    for mask, c, _ in diff_masks[1:]:
        if not np.array_equal(mask, base_mask):
            mask_const = False
        if np.any(c[base_mask] != base_canvas_t[base_mask]):
            values_const = False
    print(f"tile diff mask identical across all frames: {mask_const}")
    print(f"diff-set canvas values constant across frames: {values_const}")

    # Shared-with-ref proof at frame 30 tagged dumps (same static coords).
    r30 = load("ref_short_H_hud_canvas_30.png")[665:665 + 960, 1440:1440 + 960]
    c30 = load("cand_short_H_hud_canvas_30.png")[665:665 + 960, 1440:1440 + 960]
    same_at_set = not np.any(r30[base_mask] != c30[base_mask])
    print(f"ref canvas equals cand canvas on the stroke set (f30): {same_at_set}")
    print("GHOSTING_GATE:",
          "PASS" if (all_ok and stable and art_varies) else "FAIL")

    # Localize the static tile diffs (frame-invariant count => static cause)
    f = FRAMES[0]
    m = metas[f]
    gx, gy, gw, gh = m["x"], m["y"], m["w"], m["h"]
    canvas = load_canvas(f)[gy:gy + gh, gx:gx + gw]
    truth = load(f"compose_full_cand_f{f}.png")[gy:gy + gh, gx:gx + gw]
    gauge_img = Image.open(str(OUT / f"gauge_capture_f{f}.png")).convert("RGBA")
    exp = np.asarray(Image.alpha_composite(Image.fromarray(truth), gauge_img))
    d = np.any(canvas != exp, axis=-1)
    ys_, xs_ = np.where(d)
    print(f"-- localize f{f}: {len(ys_)} px")
    print(f"   bbox x[{xs_.min() + gx}..{xs_.max() + gx}] "
          f"y[{ys_.min() + gy}..{ys_.max() + gy}]")
    # cluster by connected column bands
    order = np.argsort(xs_)
    xs_s = xs_[order]
    bands = []
    start = prev = int(xs_s[0])
    for xv in xs_s[1:]:
        xv = int(xv)
        if xv - prev <= 3:
            prev = xv
            continue
        bands.append((start, prev))
        start = prev = xv
    bands.append((start, prev))
    for bx0, bx1 in bands[:10]:
        sel = (xs_ >= bx0) & (xs_ <= bx1)
        yy = ys_[sel]
        print(f"   band x[{bx0 + gx}..{bx1 + gx}] "
              f"y[{yy.min() + gy}..{yy.max() + gy}] n={int(sel.sum())}")
    for i in range(0, min(len(ys_), 8)):
        y, x = ys_[i], xs_[i]
        print(f"   ({x + gx},{y + gy}) canvas={tuple(int(v) for v in canvas[y, x])} "
              f"exp={tuple(int(v) for v in exp[y, x])} "
              f"gaugeA={int(np.asarray(gauge_img)[y, x][3])} "
              f"truth={tuple(int(v) for v in truth[y, x])}")
    return 0 if (all_ok and stable and art_varies) else 1


if __name__ == "__main__":
    raise SystemExit(main())
