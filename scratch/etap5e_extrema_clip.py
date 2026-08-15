"""ETAP 5E — measure getextrema cost + paste clipping identity."""
from __future__ import annotations

import time

from PIL import Image

W, H = 3840, 2160


def bench_extrema():
    for w, h, name in [(691, 691, "map"), (648, 648, "gauge"), (1160, 511, "chart")]:
        ov = Image.new("RGBA", (w, h), (200, 100, 50, 255))
        iters = 100
        t0 = time.perf_counter()
        for _ in range(iters):
            ov.getextrema()[-1]
        full = (time.perf_counter() - t0) / iters * 1000
        t0 = time.perf_counter()
        for _ in range(iters):
            ov.getchannel("A").getextrema()
        chan = (time.perf_counter() - t0) / iters * 1000
        print(f"{name} {w}x{h}: getextrema[-1] {full*1000:.1f}us | getchannel(A).getextrema {chan*1000:.1f}us")


def clipping_identity():
    """For a fully-opaque widget partially outside canvas: paste == alpha_composite?"""
    rng = 1234
    ok_all = True
    for ox, oy, tag in [(-100, -100, "top-left"), (W-50, H-50, "bottom-right"),
                        (-50, 200, "left"), (W-60, 100, "right"),
                        (300, -80, "top"), (500, H-40, "bottom")]:
        ov = Image.new("RGBA", (691, 691))
        import random
        r = random.Random(rng)
        p = ov.load()
        for y in range(691):
            for x in range(691):
                p[x, y] = (r.randint(0, 255), r.randint(0, 255), r.randint(0, 255), 255)
        base_a = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        base_p = base_a.copy()
        base_a.alpha_composite(ov, (ox, oy))
        base_p.paste(ov, (ox, oy))
        same = base_a.tobytes() == base_p.tobytes()
        print(f"clip {tag} ({ox},{oy}): paste==composite: {same}")
        ok_all &= same
    return ok_all


bench_extrema()
print("---")
ok = clipping_identity()
print("clipping identity ALL:", "PASS" if ok else "FAIL")
