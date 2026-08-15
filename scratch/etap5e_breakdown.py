"""ETAP 5E — break down Pillow alpha_composite method cost: crop / blend / paste."""
from __future__ import annotations

import time

from PIL import Image

W, H = 3840, 2160
# semi-transparent-ish widget (realistic: some opaque, some semi, some transparent)
def widget(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    import random
    r = random.Random(5)
    for y in range(h):
        for x in range(w):
            a = r.choice((0, 40, 128, 255, 220, 255))
            px[x, y] = (r.randint(0, 255), r.randint(0, 255), r.randint(0, 255), a)
    return im


def bench(name, w, h, iters=25):
    ov = widget(w, h)
    ox, oy = 500, 300
    # 1) full method
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    t0 = time.perf_counter()
    for _ in range(iters):
        base.alpha_composite(ov, (ox, oy))
    method = (time.perf_counter() - t0) / iters * 1000

    # 2) manual crop->blend->paste
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    box = (ox, oy, ox + ov.width, oy + ov.height)
    t0 = time.perf_counter()
    for _ in range(iters):
        bg = base.crop(box)
        res = Image.alpha_composite(bg, ov)
        base.paste(res, box)
    manual = (time.perf_counter() - t0) / iters * 1000

    # 3) sub-ops separately
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    t0 = time.perf_counter()
    for _ in range(iters):
        base.crop(box)
    crop = (time.perf_counter() - t0) / iters * 1000

    bg = Image.new("RGBA", ov.size, (0, 0, 0, 0))
    t0 = time.perf_counter()
    for _ in range(iters):
        Image.alpha_composite(bg, ov)
    blend = (time.perf_counter() - t0) / iters * 1000

    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    t0 = time.perf_counter()
    for _ in range(iters):
        base.paste(ov, (ox, oy))
    paste = (time.perf_counter() - t0) / iters * 1000

    print(f"{name} {w}x{h}: method {method:.3f} | manual {manual:.3f} | crop {crop:.3f} blend {blend:.3f} paste {paste:.3f}")


for name, w, h in [("map", 691, 691), ("gauge", 648, 648), ("chart", 1160, 511), ("text", 316, 51)]:
    bench(name, w, h)
