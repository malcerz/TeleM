# ETAP 2A diagnostic: point-sample ref vs cand HUD canvases around the
# residual diff strip x[1445..1743] y[1575..1621] to identify which widget
# owns the missing alpha=170 black pixels (gauge shadow vs dist_visual bar).
import glob
import os
import sys

from PIL import Image

BASE = r"c:\_DEV\TeleM\scratch\etap2a_test"


def find_canvas(tag: str, frame: int = 30) -> str:
    """Find the 3840x2160 HUD canvas dump for a given frame of ref/cand."""
    p = os.path.join(BASE, f"{tag}_short_H_hud_canvas_{frame}.png")
    if not os.path.exists(p):
        print(f"!! missing {p}")
        sys.exit(2)
    return p


ref_p = find_canvas("ref")
cand_p = find_canvas("cand")
print("REF :", ref_p)
print("CAND:", cand_p)
ref = Image.open(ref_p).convert("RGBA").load()
cand = Image.open(cand_p).convert("RGBA").load()

POINTS = [
    ("A bar∩gauge right outside strip", 2000, 1600),
    ("J bar∩gauge far right           ", 2300, 1600),
    ("B inside strip                  ", 1500, 1600),
    ("C inside strip dense col        ", 1596, 1600),
    ("C2 strip bottom row             ", 1596, 1618),
    ("D bar below gauge bbox          ", 2000, 1636),
    ("E bar left of gauge bbox        ", 1390, 1560),
    ("F just left of gauge bbox       ", 1439, 1600),
    ("G just right of strip          ", 1744, 1600),
    ("H gauge center dial            ", 1920, 1145),
    ("I gauge bbox empty corner      ", 1450, 700),
]
print(f"{'label':34s} {'REF':>18s} {'CAND':>18s}")
for label, x, y in POINTS:
    print(f"{label} ({x:4d},{y:4d}) {str(ref[x, y]):>18s} {str(cand[x, y]):>18s}")

print("\ncolumn x=1596, y=1570..1625 (ref | cand):")
for y in range(1570, 1626, 5):
    print(f"  y={y}: {ref[1596, y]} | {cand[1596, y]}")

print("\nrow y=1618, x=1440..1760 step 20 (ref | cand):")
for x in range(1440, 1761, 20):
    print(f"  x={x}: {ref[x, 1618]} | {cand[x, 1618]}")

# Bar uniformity probe: does REF look identical along the bar at y=1600?
print("\nREF row y=1600 across full bar x=1380..2460 step 60:")
row = [ref[x, 1600] for x in range(1380, 2461, 60)]
uniq = {}
for px in row:
    uniq[px] = uniq.get(px, 0) + 1
print(" unique:", uniq)

# Same row in CAND
print("CAND row y=1600 across full bar x=1380..2460 step 60:")
row = [cand[x, 1600] for x in range(1380, 2461, 60)]
uniq = {}
for px in row:
    uniq[px] = uniq.get(px, 0) + 1
print(" unique:", uniq)