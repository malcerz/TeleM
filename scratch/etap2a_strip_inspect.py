"""Inspect the residual diff strip: what content differs ref vs cand."""
import numpy as np
from PIL import Image
from pathlib import Path

OUT = Path("scratch/etap2a_test")
a = np.array(Image.open(OUT / "ref_short_H_hud_canvas_30.png").convert("RGBA"))
b = np.array(Image.open(OUT / "cand_short_H_hud_canvas_30.png").convert("RGBA"))

# Diff strip
y0, y1, x0, x1 = 1575, 1622, 1445, 1744
sa, sb = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
d = np.abs(sa.astype(np.int16) - sb.astype(np.int16))
diff = np.any(d > 0, axis=-1)
print(f"strip {x1-x0}x{y1-y0}, diff px: {int(diff.sum())}")

# Column/row profile of diff density
cols = diff.mean(axis=0)
rows = diff.mean(axis=1)
print("row density:", " ".join(f"{v:.2f}" for v in rows))
print("col nonzero ranges:")
on = np.nonzero(cols > 0)[0]
if len(on):
    # find contiguous runs
    runs, start = [], on[0]
    for i in range(1, len(on)):
        if on[i] != on[i-1] + 1:
            runs.append((start, on[i-1])); start = on[i]
    runs.append((start, on[-1]))
    for r in runs:
        print(f"  x[{x0+r[0]}..{x0+r[1]}] width={r[1]-r[0]+1}")

# Sample center pixel rows from a dense column
dense_col = int(np.argmax(cols)) + x0
print(f"densest col abs x={dense_col}")
for yy in range(y0, y1, 6):
    pa = a[yy, dense_col]; pb = b[yy, dense_col]
    print(f"  y={yy} ref={tuple(int(v) for v in pa)} cand={tuple(int(v) for v in pb)}")

# Save 4x enlarged strips for visual inspection
Image.fromarray(np.kron(sa, np.ones((4,4,1),dtype=np.uint8))).save(OUT/"strip_ref_x4.png")
Image.fromarray(np.kron(sb, np.ones((4,4,1),dtype=np.uint8))).save(OUT/"strip_cand_x4.png")

# Alpha stats in strip
print("ref alpha range in strip:", int(sa[...,3].min()), int(sa[...,3].max()))
print("cand alpha range in strip:", int(sb[...,3].min()), int(sb[...,3].max()))
