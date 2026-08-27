"""ETAP 2C quick unit probes: renderer record + tile mapping + merge."""
import sys

sys.path.insert(0, ".")

from src.indicators.gauge import (  # noqa: E402
    _render_gauge_indicator,
    get_gauge_dynamic_info,
)
from src.ffmpeg.amd_native_exporter import (  # noqa: E402
    _support_to_tile_rect,
    _union_tile_rects,
    _merge_tile_rects,
)

FONT = "C:/Windows/Fonts/arial.ttf"


def render_speed(key, value, size_px, cfg_over=None, ss=1):
    cfg = {"x": 0.78, "y": 0.62, "size": 0.22}
    if cfg_over:
        cfg.update(cfg_over)
    return _render_gauge_indicator(
        3840, 2160, {}, FONT, key, value, "km/h", "SPEED",
        cfg, 1080, 2, 42, None, 0.0, 70.0, 5, 8, size_px, ss,
        formatted_val=f"{value:.1f}")


# 1) speed gauge renders and records dynamic info
img, x, y, extra = render_speed("fit_enhanced_speed_text", 42.7, 240)
info = get_gauge_dynamic_info("fit_enhanced_speed_text")
assert info is not None, "no record"
assert info["kind"] == "speed" and info["supported"] is True
assert info["sig"] is not None and len(info["sig"]) >= 20
w, h = img.size
nb, tb = info["needle_bbox"], info["text_bbox"]
print("widget", img.size, "needle", [round(v, 1) for v in nb],
      "text", [round(v, 1) for v in tb])
assert nb is not None, "needle support missing"
assert nb[2] > nb[0] and nb[3] > nb[1], nb
assert -4 <= nb[0] and nb[2] <= w + 4 and -4 <= nb[1] and nb[3] <= h + 4, (
    "needle outside widget", nb, w, h)
if tb is not None:
    assert tb[2] > tb[0] and tb[3] > tb[1], tb
    assert -2 <= tb[0] and tb[2] <= w + 2 and -2 <= tb[1] and tb[3] <= h + 2, (
        "text outside widget", tb, w, h)

# 2) second value -> same sig (style unchanged)
_img2, _, _, _ = render_speed("k2", 63.4, 240)
i2 = get_gauge_dynamic_info("k2")
assert i2["sig"] == info["sig"], "sig must be value-independent"

# 3) style change -> sig changes
_img3, _, _, _ = render_speed("k3", 42.7, 240, {"needle_color": "#00FF00"})
i3 = get_gauge_dynamic_info("k3")
assert i3["sig"] != info["sig"], "sig must capture style params"

# 4) size change -> sig changes + supports scale
_img4, _, _, _ = render_speed("k4", 42.7, 480)
i4 = get_gauge_dynamic_info("k4")
assert i4["sig"] != info["sig"], "sig must capture geometry"
n4 = i4["needle_bbox"]
assert (n4[2] - n4[0]) > (nb[2] - nb[0]), "needle band must scale with size"

# 5) compass records unsupported
_imgc, _, _, _ = _render_gauge_indicator(
    1920, 1080, {}, FONT, "compass_probe", 90.0, "deg", "HDG",
    {"gauge_style": "compass", "x": 0.5, "y": 0.5, "size": 0.1},
    1080, 2, 30, None, 0.0, 360.0, 8, 6, 120, 1)
ic = get_gauge_dynamic_info("compass_probe")
assert ic is not None and ic["kind"] == "compass" and ic["supported"] is False
print("compass record OK:", ic["kind"], ic["supported"])

# 6) tile mapping incl. clip offsets and clamping
r = _support_to_tile_rect((10.2, 20.7, 30.9, 40.1), 0, 0, 100, 100)
assert r == (9, 19, 32, 42), r  # floor-1 / ceil+1 safety margin
r2 = _support_to_tile_rect((10, 10, 30, 30), 15, 15, 50, 50)
assert r2 == (0, 0, 16, 16), r2  # shifted by clip offset, clamped to tile
assert _support_to_tile_rect(None, 0, 0, 10, 10) is None
# zero-width support is intentionally grown by the safety margin so
# hairline dynamic art never loses coverage:
assert _support_to_tile_rect((5, 5, 5, 8), 0, 0, 10, 10) == (4, 4, 6, 9)
assert _support_to_tile_rect("junk", 0, 0, 10, 10) is None  # malformed safe
print("tile mapping OK")


def covered(rect, rects):
    (rx0, ry0, rx1, ry1) = rect
    return any(x0 <= rx0 and y0 <= ry0 and rx1 <= x1 and ry1 <= y1
               for (x0, y0, x1, y1) in rects)


# 7) merge keeps superset guarantee
a, b = (0, 0, 10, 10), (12, 12, 20, 20)
m = _merge_tile_rects([a, b], max_rects=1)
assert covered(a, m) and covered(b, m), m
# Under the rect cap, inputs stay untouched (fewer crops is not worth
# extra growth); merging is a reduction strategy used when over the cap.
m2 = _merge_tile_rects([(0, 0, 10, 10), (5, 5, 15, 15)], max_rects=8)
assert m2 == [(0, 0, 10, 10), (5, 5, 15, 15)], m2
src4 = [(0, 0, 4, 4), (6, 6, 9, 9), (12, 0, 14, 3), (20, 20, 22, 24)]
m3 = _merge_tile_rects(src4, max_rects=2)
for src in src4:
    assert covered(src, m3), (src, m3)
assert len(m3) <= 2
assert _merge_tile_rects([], 8) == []
print("merge OK", m, "|", m2, "|", m3)

print("ALL UNIT PROBES PASS")
