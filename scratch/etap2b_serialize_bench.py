"""ETAP 2B pre-design microbenchmark v2: gauge transfer options.

Methodology fixes vs v1: gc disabled, 200 reps, min/p50/p95 reported,
preallocated diff buffers, fixed-region crop variant (no per-frame diff).
"""
import gc
import time

import numpy as np
from PIL import Image, ImageDraw

W = H = 960
REPS = 200

gc.disable()


def make_image(angle_deg: float) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, W - 40, H - 40), outline=(200, 200, 200, 255), width=12)
    for i in range(60):
        a = np.deg2rad(i * 6)
        r0, r1 = 60, 90
        cx = cy = W / 2
        d.line((cx + r0 * np.cos(a), cy + r0 * np.sin(a),
                cx + r1 * np.cos(a), cy + r1 * np.sin(a)),
               fill=(180, 180, 180, 220), width=3)
    a = np.deg2rad(135 + angle_deg * 270 / 100.0)
    cx = cy = W / 2
    d.line((cx, cy, cx + 330 * np.cos(a), cy + 330 * np.sin(a)),
           fill=(255, 60, 60, 255), width=8)
    d.text((W / 2 - 60, H - 160), f"{angle_deg:05.2f}", fill=(255, 255, 255, 255))
    return img


def bench(fn, n=REPS):
    for _ in range(5):
        fn()
    samples = []
    out = None
    for _ in range(n):
        t0 = time.perf_counter()
        out = fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    s = sorted(samples)
    return {"min": s[0], "p50": s[n // 2], "p95": s[int(n * 0.95)]}, out


imgs = [make_image(float(v)) for v in (10, 11, 12)]
prev_img, cur_img = imgs[0], imgs[1]

res_A, b_A = bench(lambda: cur_img.tobytes("raw", "RGBA"))
res_B, arr_B = bench(lambda: np.asarray(cur_img))

prev = np.asarray(prev_img)
cur = np.asarray(cur_img)
p32 = prev.view(np.uint32).reshape(H, W)
c32 = cur.view(np.uint32).reshape(H, W).copy()
ne_buf = np.empty((H, W), dtype=bool)


def diff_full():
    np.not_equal(c32, p32, out=ne_buf)
    if not ne_buf.any():
        return None
    ys, xs = np.nonzero(ne_buf)
    return xs.min(), ys.min(), xs.max(), ys.max(), ys.size


res_D, bbox = bench(diff_full)

FIX = (120, 300, 760, 560)  # x,y,w,h covering dial center + value strip


def fixed_crop_bytes():
    return cur_img.crop(
        (FIX[0], FIX[1], FIX[0] + FIX[2], FIX[1] + FIX[3])
    ).tobytes("raw", "RGBA")


res_F, b_F = bench(fixed_crop_bytes)

x0, y0, x1, y1, npx = bbox
print(f"A full tobytes        min={res_A['min']:6.3f} p50={res_A['p50']:6.3f} "
      f"p95={res_A['p95']:6.3f} ms ({len(b_A)/1e6:.2f} MB)")
print(f"B np.asarray          min={res_B['min']:6.3f} p50={res_B['p50']:6.3f} "
      f"p95={res_B['p95']:6.3f} ms")
print(f"D diff(out)+any+nonz  min={res_D['min']:6.3f} p50={res_D['p50']:6.3f} "
      f"p95={res_D['p95']:6.3f} ms (changed={npx}, bbox={x1-x0+1}x{y1-y0+1})")
print(f"F fixed {FIX} crop+tobytes min={res_F['min']:6.3f} "
      f"p50={res_F['p50']:6.3f} p95={res_F['p95']:6.3f} ms ({len(b_F)/1e6:.2f} MB)")
