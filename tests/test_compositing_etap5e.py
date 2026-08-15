"""ETAP 5E: final-compositing layer must be byte-identical to the legacy path.

Covers the controlled alpha cases, canvas clipping, widget overlap and the
transparent-destination paste fast path.  ``composite_final`` runs in
OPTIMIZED mode; every case is compared against the legacy ``alpha_composite``
result and must be byte-identical.
"""
from __future__ import annotations

import random

from PIL import Image

from src.indicators.rotated_paste import composite_final, set_composite_mode

W, H = 3840, 2160


def _widget(w, h, alpha, seed=1, filled=True):
    """Semi-transparent widget with a filled content block."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    r = random.Random(seed)
    if filled:
        for y in range(h):
            for x in range(w):
                px[x, y] = (r.randint(0, 255), r.randint(0, 255), r.randint(0, 255), alpha)
    else:
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                px[x, y] = (r.randint(0, 255), r.randint(0, 255), r.randint(0, 255), alpha)
    return im


def _reference(base, overlay, x, y):
    ref = base.copy()
    ref.alpha_composite(overlay, (x, y))
    return ref


def _optimized(base, overlay, x, y, prior_bboxes=None):
    opt = base.copy()
    set_composite_mode("OPTIMIZED")
    composite_final(opt, overlay, x, y, prior_bboxes=prior_bboxes, cache_key="test")
    set_composite_mode("REFERENCE")
    return opt


def _assert_same(ref, opt):
    assert ref.tobytes() == opt.tobytes()


def _transparent_base():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def _bg_base():
    b = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    b.paste((30, 60, 90, 200), (0, 0, W, H))
    return b


def test_alpha_0_transparent_dest():
    base = _transparent_base()
    ov = _widget(100, 80, 0)
    _assert_same(_reference(base, ov, 100, 100), _optimized(base, ov, 100, 100, []))


def test_alpha_1_transparent_dest():
    # transparent dest -> paste fast path (alpha_min>0)
    base = _transparent_base()
    ov = _widget(100, 80, 1)
    _assert_same(_reference(base, ov, 100, 100), _optimized(base, ov, 100, 100, []))


def test_alpha_1_over_background():
    # non-transparent dest -> composite path forced via overlapping prior bbox
    base = _bg_base()
    ov = _widget(100, 80, 1)
    _assert_same(_reference(base, ov, 100, 100), _optimized(base, ov, 100, 100, [(100, 100, 100, 80)]))


def test_alpha_64():
    base = _bg_base()
    ov = _widget(100, 80, 64)
    _assert_same(_reference(base, ov, 100, 100), _optimized(base, ov, 100, 100, [(100, 100, 100, 80)]))


def test_alpha_128():
    base = _bg_base()
    ov = _widget(100, 80, 128)
    _assert_same(_reference(base, ov, 100, 100), _optimized(base, ov, 100, 100, [(100, 100, 100, 80)]))


def test_alpha_254():
    base = _bg_base()
    ov = _widget(100, 80, 254)
    _assert_same(_reference(base, ov, 100, 100), _optimized(base, ov, 100, 100, [(100, 100, 100, 80)]))


def test_canvas_clipping_edges():
    base = _transparent_base()
    ov = _widget(300, 300, 128)
    for x, y in ((-100, -100), (W - 150, H - 150), (-80, 200), (W - 200, 100), (500, -90), (600, H - 120)):
        _assert_same(_reference(base, ov, x, y), _optimized(base, ov, x, y, []))


def test_overlap_two_semi_transparent_widgets():
    # production invariant: canvas fully transparent at frame start
    base = _transparent_base()
    a = _widget(400, 300, 100, seed=2)
    b = _widget(400, 300, 150, seed=3)
    ref = base.copy()
    ref.alpha_composite(a, (500, 500))
    ref.alpha_composite(b, (550, 520))
    opt = base.copy()
    set_composite_mode("OPTIMIZED")
    composite_final(opt, a, 500, 500, prior_bboxes=[], cache_key="a")
    # b overlaps a's region -> composite path (never paste)
    composite_final(opt, b, 550, 520, prior_bboxes=[(500, 500, 400, 300)], cache_key="b")
    set_composite_mode("REFERENCE")
    _assert_same(ref, opt)


def test_transparent_dest_paste_fast_path_opaque_source():
    """Widget with alpha_min>0 and transparent dest -> paste == alpha_composite."""
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov = _widget(400, 300, 220, seed=5)  # no fully-transparent pixels
    _assert_same(_reference(base, ov, 1000, 800), _optimized(base, ov, 1000, 800, []))


def test_transparent_dest_paste_fast_path_map_like():
    """Opaque background + semi-transparent route -> paste == alpha_composite over
    transparent dest (same byte result)."""
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov = Image.new("RGBA", (400, 400), (30, 30, 30, 255))  # opaque bg
    px = ov.load()
    r = random.Random(9)
    for i in range(40):  # semi-transparent 'route'
        for j in range(0, 400, 2):
            px[j, i * 10 % 400] = (255, 60, 30, 220)
    _assert_same(_reference(base, ov, 1200, 900), _optimized(base, ov, 1200, 900, []))


def test_reference_mode_is_legacy():
    set_composite_mode("REFERENCE")
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov = _widget(100, 80, 128)
    out = base.copy()
    composite_final(out, ov, 10, 10, prior_bboxes=[], cache_key="x")
    ref = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ref.alpha_composite(ov, (10, 10))
    _assert_same(ref, out)
    set_composite_mode("OPTIMIZED")
