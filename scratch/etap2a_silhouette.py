# ETAP 2A: silhouette of the residual REF-only structure + context crops.
import os

from PIL import Image

BASE = r"c:\_DEV\TeleM\scratch\etap2a_test"
ref = Image.open(os.path.join(BASE, "ref_short_H_hud_canvas_30.png")).convert("RGBA")
cand = Image.open(os.path.join(BASE, "cand_short_H_hud_canvas_30.png")).convert("RGBA")
rp, cp = ref.load(), cand.load()

# 1) Exact silhouette of non-transparent pixels in window x[1400..1800], y[1540..1660]
print("REF silhouette rows (x-range of alpha>0 within window):")
for y in range(1540, 1661, 4):
    xs = [x for x in range(1400, 1801) if rp[x, y][3] > 0]
    if xs:
        vals = {rp[x, y] for x in xs[:400]}
        print(f"  y={y}: x[{xs[0]}..{xs[-1]}] n={len(xs)} colors~{list(vals)[:3]}")
    else:
        print(f"  y={y}: -")

# 2) Same-window diff sanity: confirm cand empty wherever ref painted
mism = sum(
    1
    for y in range(1540, 1661)
    for x in range(1400, 1801)
    if rp[x, y] != cp[x, y]
)
print(f"\nwindow mismatches ref!=cand: {mism}")

# 3) Context crops for visual identification
for name, img in (("ref", ref), ("cand", cand)):
    crop = img.crop((1300, 1380, 2620, 1720))
    crop.resize((crop.width * 2, crop.height * 2), Image.NEAREST).save(
        os.path.join(BASE, f"ctx_{name}_f30.png")
    )
print("\nwrote ctx_ref_f30.png / ctx_cand_f30.png (crop 1300,1380-2620,1720 @2x)")