"""Why does the tile diff mask move between frames? Compare f100/f150/f200."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path("scratch/etap2a_test")


def tile_of(arr, m):
    return arr[m["y"]:m["y"] + m["h"], m["x"]:m["x"] + m["w"]]


def parts(f):
    with open(OUT / f"gauge_meta_f{f}.json", encoding="utf-8") as fh:
        m = json.load(fh)
    c = np.asarray(Image.open(f"H_hud_canvas_{f}.png").convert("RGBA"))
    t = np.asarray(Image.open(str(OUT / f"compose_full_cand_f{f}.png")).convert("RGBA"))
    g = Image.open(str(OUT / f"gauge_capture_f{f}.png")).convert("RGBA")
    ct, tt = tile_of(c, m), tile_of(t, m)
    e = np.asarray(Image.alpha_composite(Image.fromarray(tt), g))
    return m, ct, e


res = {}
for f in (100, 101, 102, 103, 104, 105, 150, 151, 200, 201, 250, 251, 320):
    m, c, e = parts(f)
    d = np.any(c != e, axis=-1)
    res[f] = (m, c, e, d)

print("=== tile-interior ref-vs-cand: strokes cancel, only band/tick differ ===")
import json as _json
with open(OUT / "gauge_meta_f100.json", encoding="utf-8") as fh:
    _m = _json.load(fh)
r = np.asarray(Image.open(str(OUT / "ref_short_H_hud_canvas_30.png")).convert("RGBA"))
c = np.asarray(Image.open(str(OUT / "cand_short_H_hud_canvas_30.png")).convert("RGBA"))
rt = tile_of(r, _m)
ct = tile_of(c, _m)
d_rc = np.any(rt != ct, axis=-1)
ys, xs = np.where(d_rc)
band_rows = slice(max(0, 1549 - _m["y"]), min(_m["h"], 1647 - _m["y"]))
in_band = (ys >= 1549 - _m["y"]) & (ys <= 1647 - _m["y"])
print(f"tile ref-vs-cand total={int(d_rc.sum())}")
print(f"  inside dist band rows: {int(in_band.sum())}")
print(f"  outside band rows: {int((~in_band).sum())}")
yo, xo = ys[~in_band], xs[~in_band]
if len(yo):
    print(f"  outside-band bbox x[{xo.min()},{xo.max()}] y[{yo.min()},{yo.max()}]")
