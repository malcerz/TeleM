"""ETAP 5E — verify Pillow alpha_composite semantics before optimizing.

Answers:
1. Does base.alpha_composite(overlay, (x,y)) modify base in place?
2. What is the exact blend math (straight alpha)?
3. Is crop-to-content-bbox + composite-at-offset == full composite (pixel-exact)?
4. Is paste-with-mask identical to alpha_composite (rounding)?
5. Does alpha_composite clip to canvas bounds?
6. Does it skip fully-transparent source pixels (perf relevant)?
"""
from __future__ import annotations

import time

from PIL import Image


def make(alpha, w=8, h=8, color=(200, 100, 50)):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (color[0], color[1], color[2], alpha)
    return img


def report(name, ok):
    print(f"{name}: {'PASS' if ok else 'FAIL'}")
    return ok


all_ok = True

# 1. In-place semantics
base = Image.new("RGBA", (16, 16), (10, 20, 30, 40))
ov = make(128)
ret = base.alpha_composite(ov, (2, 2))
inplace = base.getpixel((2, 2)) != (10, 20, 30, 40)
print("ret is base:", ret is base, "| in-place modified:", inplace)
all_ok &= report("in-place", inplace)

# 2. Exact math: straight-alpha "over" operator
# out_a = src_a + dst_a*(1 - src_a)
# out_c = (src_c*src_a + dst_c*dst_a*(1 - src_a)) / out_a   (round, straight alpha)
base = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
base.paste((10, 20, 30, 40), (0, 0, 16, 16))
ov = make(128)
base.alpha_composite(ov, (0, 0))
c = base.getpixel((0, 0))
sa = 128 / 255.0
out_a = 128 + 40 * (1 - sa)
out_r = (200 * 128 + 10 * 40 * (1 - sa)) / out_a
out_g = (100 * 128 + 20 * 40 * (1 - sa)) / out_a
out_b = (50 * 128 + 30 * 40 * (1 - sa)) / out_a
print("blend got:", c, "expected ~", (out_r, out_g, out_b, out_a))
all_ok &= report("blend-math", abs(c[0] - round(out_r)) <= 1 and abs(c[3] - round(out_a)) <= 1)

# 3. Crop-to-content + composite-at-offset == full composite
for alpha in (0, 1, 64, 128, 254, 255):
    base_ref = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    # pre-fill background region
    bg = Image.new("RGBA", (32, 32), (70, 80, 90, 200))
    base_ref.alpha_composite(bg, (0, 0))
    base_opt = base_ref.copy()

    ov_full = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    ov_px = ov_full.load()
    for y in range(4, 16):
        for x in range(3, 17):
            ov_px[x, y] = (150, 40, 200, alpha)

    base_ref.alpha_composite(ov_full, (5, 5))

    bbox = ov_full.getbbox()
    if bbox is None:
        same = base_ref.tobytes() == base_opt.tobytes()
        print(f"  crop-to-bbox alpha={alpha} (empty bbox): {same}")
        all_ok &= report(f"crop-eq-alpha-{alpha}", same)
        continue
    ov_crop = ov_full.crop(bbox)
    base_opt.alpha_composite(ov_crop, (5 + bbox[0], 5 + bbox[1]))

    same = base_ref.tobytes() == base_opt.tobytes()
    print(f"  crop-to-bbox alpha={alpha}: {same}")
    all_ok &= report(f"crop-eq-alpha-{alpha}", same)

# 4. paste-with-mask vs alpha_composite (rounding)
base_ref = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
base_ref.paste((12, 34, 56, 200), (0, 0, 24, 24))
base_mask = base_ref.copy()
ov = make(128)
base_ref.alpha_composite(ov, (0, 0))
base_mask.paste(ov, (0, 0), ov)  # RGB channels use mask, alpha channel: paste replaces alpha?
same_paste = base_ref.tobytes() == base_mask.tobytes()
print(f"paste-with-mask identical to alpha_composite: {same_paste}")
if not same_paste:
    for y in range(8):
        print("  ref :", [base_ref.getpixel((x, y)) for x in range(8)])
        print("  mask:", [base_mask.getpixel((x, y)) for x in range(8)])
        break

# 5. Clipping semantics
base_ref = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
base_opt = base_ref.copy()
ov = make(128, w=20, h=20)
base_ref.alpha_composite(ov, (-5, -5))  # partially off canvas top-left
base_opt.alpha_composite(ov.crop(ov.getbbox()), (0, 0))  # naive re-position? not equivalent
# Instead test: Pillow clips; check no exception and corners.
print("clip corners ref:", base_ref.getpixel((0, 0)), base_ref.getpixel((9, 9)))
all_ok &= report("clip-no-crash", True)

# 6. Does alpha_composite skip fully transparent source pixels? (timing)
w = h = 3840
transparent = Image.new("RGBA", (1200, 600), (0, 0, 0, 0))
opaque = Image.new("RGBA", (1200, 600), (200, 100, 50, 255))
dst = Image.new("RGBA", (w, h), (0, 0, 0, 0))
t0 = time.perf_counter()
for _ in range(20):
    dst.alpha_composite(transparent, (100, 100))
t_transparent = (time.perf_counter() - t0) / 20 * 1000
dst = Image.new("RGBA", (w, h), (0, 0, 0, 0))
t0 = time.perf_counter()
for _ in range(20):
    dst.alpha_composite(opaque, (100, 100))
t_opaque = (time.perf_counter() - t0) / 20 * 1000
print(f"alpha_composite 1200x600 fully-transparent: {t_transparent:.3f} ms/call")
print(f"alpha_composite 1200x600 fully-opaque:      {t_opaque:.3f} ms/call")
all_ok &= report("transparent-cheaper-or-equal", t_transparent <= t_opaque * 1.5)

print("\nALL:", "PASS" if all_ok else "FAIL")
