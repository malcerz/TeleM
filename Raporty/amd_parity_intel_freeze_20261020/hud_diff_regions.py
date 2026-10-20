"""Locate pixel differences between two final MP4 frames (same source frame).

Prints connected difference regions so a HUD change can be shown to be
confined to the intended widgets (here: temperature values).
"""
import json, subprocess, sys
import numpy as np
from PIL import Image

ff, a, b, t, out_prefix = sys.argv[1:6]
W, H = 3840, 2160

def frame(p):
    raw = subprocess.run([ff, "-v", "error", "-ss", t, "-i", p, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "yuv420p10le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<u2")[:W*H].reshape(H, W).astype(np.int32)

ya, yb = frame(a), frame(b)
d = np.abs(ya - yb)
BS = 32
blk = d[:H//BS*BS, :W//BS*BS].reshape(H//BS, BS, W//BS, BS).max(axis=(1, 3)) > 200
# 4-connected labelling of changed blocks
lab = np.zeros(blk.shape, int); n = 0; regions = []
for (r, c) in zip(*np.nonzero(blk)):
    if lab[r, c]:
        continue
    n += 1; stack = [(r, c)]; lab[r, c] = n; cells = []
    while stack:
        y, x = stack.pop(); cells.append((y, x))
        for yy, xx in ((y+1, x), (y-1, x), (y, x+1), (y, x-1)):
            if 0 <= yy < blk.shape[0] and 0 <= xx < blk.shape[1] and blk[yy, xx] and not lab[yy, xx]:
                lab[yy, xx] = n; stack.append((yy, xx))
    ys, xs = zip(*cells)
    regions.append({"x0": min(xs)*BS, "y0": min(ys)*BS, "x1": (max(xs)+1)*BS, "y1": (max(ys)+1)*BS, "blocks": len(cells)})
regions.sort(key=lambda r: -r["blocks"])
print(json.dumps(default=int, obj={"Y_MAE_full": float(d.mean()), "Y_max": int(d.max()),
                  "pixels_diff_gt200": int((d > 200).sum()), "regions": regions[:12]}, indent=1))
for i, r in enumerate(regions[:4]):
    pad = 24
    box = (max(0, r["x0"]-pad), max(0, r["y0"]-pad), min(W, r["x1"]+pad), min(H, r["y1"]+pad))
    for tag, y in (("A", ya), ("B", yb)):
        crop = (np.clip(y[box[1]:box[3], box[0]:box[2]] / 4, 0, 255)).astype(np.uint8)
        Image.fromarray(crop).save(f"{out_prefix}_region{i}_{tag}.png")
