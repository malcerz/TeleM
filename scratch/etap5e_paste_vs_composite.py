"""ETAP 5E — measure paste vs alpha_composite for fully-opaque widgets."""
from __future__ import annotations

import random
import time

from PIL import Image

W = 3840
H = 2160


def opaque_widget(w, h):
    im = Image.new("RGBA", (w, h))
    px = im.load()
    rnd = random.Random(7)
    for y in range(h):
        for x in range(w):
            px[x, y] = (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255), 255)
    return im


def check_identity(w, h):
    """paste == alpha_composite for a fully-opaque widget?"""
    ov = opaque_widget(w, h)
    base_a = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # pre-fill with a gradient so dst is non-trivial
    bg = Image.new("RGBA", (W, H))
    bp = bg.load()
    for y in range(0, H, 8):
        for x in range(0, W, 8):
            bp[x, y] = (x % 256, y % 256, 128, 200)
    base_a.alpha_composite(bg, (0, 0))
    base_p = base_a.copy()

    ox, oy = 500, 300
    base_a.alpha_composite(ov, (ox, oy))
    base_p.paste(ov, (ox, oy))

    da = base_a.tobytes()
    dp = base_p.tobytes()
    mism = sum(1 for i in range(0, len(da), 4) if da[i:i+4] != dp[i:i+4])
    return mism == 0, mism


def bench(w, h, iters=30):
    ov = opaque_widget(w, h)
    # composite
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    t0 = time.perf_counter()
    for _ in range(iters):
        base.alpha_composite(ov, (500, 300))
    comp_ms = (time.perf_counter() - t0) / iters * 1000
    # paste
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    t0 = time.perf_counter()
    for _ in range(iters):
        base.paste(ov, (500, 300))
    paste_ms = (time.perf_counter() - t0) / iters * 1000
    return comp_ms, paste_ms


for w, h, name in [(691, 691, "map"), (648, 648, "gauge"), (1160, 511, "chart")]:
    ok, mism = check_identity(w, h)
    comp, paste = bench(w, h)
    print(f"{name} {w}x{h}: paste==composite: {ok} (mism {mism}) | composite {comp:.3f}ms paste {paste:.3f}ms | speedup {comp/max(paste,1e-9):.2f}x")

# also: crop-to-bbox timing benefit for a 92%-content widget
ov_full = opaque_widget(1160, 511)
# make a 8%-transparent-margin version
ov_trim = ov_full.copy()
ov_trim.paste((0, 0, 0, 0), (0, 0, 1160, 2))
ov_trim.paste((0, 0, 0, 0), (1156, 0, 1160, 511))
ov_trim.paste((0, 0, 0, 0), (0, 474, 1160, 511))
bb = ov_trim.getbbox()
ov_c = ov_trim.crop(bb)
base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
iters = 30
t0 = time.perf_counter()
for _ in range(iters):
    base.alpha_composite(ov_trim, (500, 300))
full_ms = (time.perf_counter() - t0) / iters * 1000
t0 = time.perf_counter()
for _ in range(iters):
    base.alpha_composite(ov_c, (500 + bb[0], 300 + bb[1]))
crop_ms = (time.perf_counter() - t0) / iters * 1000
print(f"chart full {full_ms:.3f}ms vs crop-to-bbox({bb}) {crop_ms:.3f}ms | save {full_ms-crop_ms:.3f}ms")
