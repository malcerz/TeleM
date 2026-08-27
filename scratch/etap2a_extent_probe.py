# ETAP 2A: full-extent probe of the REF-only line+tick structure.
import os

from PIL import Image

BASE = r"c:\_DEV\TeleM\scratch\etap2a_test"
ref = Image.open(os.path.join(BASE, "ref_short_H_hud_canvas_30.png")).convert("RGBA").load()
cand = Image.open(os.path.join(BASE, "cand_short_H_hud_canvas_30.png")).convert("RGBA").load()


def runs(px, y=None, x=None, lo=0, hi=3840, thresh=8):
    """Alpha>thresh run-length list along a row (y) or column (x)."""
    out = []
    start = None
    rng = range(lo, hi)
    for i in rng:
        a = px[i, y][3] if y is not None else px[x, i][3]
        if a > thresh and start is None:
            start = i
        elif a <= thresh and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, hi - 1))
    return out


print("ROW y=1618 alpha runs (x-extent of the horizontal line):")
print("  REF :", runs(ref, y=1618))
print("  CAND:", runs(cand, y=1618))

print("\nROW y=1600 alpha runs:")
print("  REF :", runs(ref, y=1600))
print("  CAND:", runs(cand, y=1600))

print("\nCOL x=1597 alpha runs y[1500..2050] (tick + below):")
print("  REF :", runs(ref, x=1597, lo=1500, hi=2050))
print("  CAND:", runs(cand, x=1597, lo=1500, hi=2050))

print("\nCOL x=1460 alpha runs y[1500..2050] (line left part, below):")
print("  REF :", runs(ref, x=1460, lo=1500, hi=2050))
print("  CAND:", runs(cand, x=1460, lo=1500, hi=2050))

print("\nCOL x=1700 alpha runs y[1500..2050] (line right part, below):")
print("  REF :", runs(ref, x=1700, lo=1500, hi=2050))
print("  CAND:", runs(cand, x=1700, lo=1500, hi=2050))

# Sample colors along the line outside the strip window (x>1800) if any
print("\nREF samples row y=1618: x=1900:", ref[1900, 1618], " x=2400:", ref[2400, 1618])
print("CAND samples row y=1618: x=1900:", cand[1900, 1618], " x=2400:", cand[2400, 1618])