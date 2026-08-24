"""ETAP 14 — configurable rotation pivot for the Przechył / Lean graphic.

Contract:
- The graphic no longer rotates rigidly around its centre by default.
- ``pivot_x`` / ``pivot_y`` (0..1, normalised to the graphic) control the
  rotation point; the default is bottom-centre (0.5 / 1.0) so the bike looks
  "planted at the ground".
- Preview and final render share the same pivot logic.
- Old configs without the fields get the defaults and keep rendering.
"""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest
from PIL import Image, ImageChops

from src.gui.qt.models import FORM_SCHEMA_MAP, canonical_defaults
from src.indicators.compositor import compose_overlay
from src.indicators.lean import (
    _graphic_pivot,
    _render_lean_indicator,
    _rotate_paste_params,
)


def _lean_cfg(**over):
    cfg = {
        "enabled": True, "form": "lean", "label": "PRZECHYŁ", "unit": "°",
        "source": "gyro", "axis": "x", "sensitivity": 1.0, "max_angle": 30.0,
        "zero_offset": 0.0, "invert_axis": False,
        "pivot_x": 0.5, "pivot_y": 1.0,
        "graphic": "beam", "show_value": True, "show_reference": True,
        "show_ticks": True, "decimals": 0, "track_color": "#FFFFFF",
        "marker_color": "#FFFFFF", "x": 50.0, "y": 50.0, "size": 14.0,
        "rotation": 0, "font_size": 1.2,
    }
    cfg.update(over)
    return cfg


def _render(cfg, value=10.0, canvas=(1280, 720), formatted=None):
    w, h = canvas
    return _render_lean_indicator(
        w, h, {"global": {}, "indicators": {"probe": cfg}}, "",
        "probe", value, "°", "PRZECHYŁ", cfg, min(w, h), 2,
        max(8, round(20.0 / 100.0 * h)), None, 0.0, 90.0, 0, 2,
        round(cfg.get("size", 14.0) / 100.0 * w), 1,
        formatted_val=formatted,
    )[0]


def _graphic_only_cfg(**over):
    # only the graphic: no title / reference / ticks / value text
    return _lean_cfg(show_value=False, show_reference=False, show_ticks=False,
                     show_label=False, **over)


# ---------------------------------------------------------------------------
# TEST 1 — DEFAULT PIVOT (0.5 / 1.0)
# ---------------------------------------------------------------------------

def test_default_pivot_is_bottom_center():
    dflt = canonical_defaults(FORM_SCHEMA_MAP["lean"]())
    assert dflt["pivot_x"] == 0.5
    assert dflt["pivot_y"] == 1.0


def test_graphic_pivot_uses_defaults_when_absent():
    # old config without the fields -> defaults (0.5, 1.0)
    px, py = _graphic_pivot(_lean_cfg(), 200, 100)
    assert px == pytest.approx(100.0)
    assert py == pytest.approx(100.0)
    px2, py2 = _graphic_pivot(_lean_cfg(pivot_x=0.25, pivot_y=0.0), 200, 100)
    assert px2 == pytest.approx(50.0)
    assert py2 == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TEST 2 — CENTER vs BOTTOM actually use a different pivot
# ---------------------------------------------------------------------------

def test_rotate_paste_math_center_vs_bottom():
    gw, gh = 200, 100
    # pivot = centre  -> screen pivot is the graphic centre
    _p, _px, _py, sx_c, sy_c = _rotate_paste_params(gw, gh, 100.0, 50.0, 400, 200.0)
    assert sx_c == pytest.approx(400.0 / 2.0)
    assert sy_c == pytest.approx(200.0)
    # pivot = bottom-centre -> screen pivot is the bottom of the centred graphic
    _p2, _px2, _py2, sx_b, sy_b = _rotate_paste_params(gw, gh, 100.0, 100.0, 400, 200.0)
    assert sx_b == pytest.approx(400.0 / 2.0)
    assert sy_b == pytest.approx(200.0 + 50.0)


def test_center_vs_bottom_pivot_render_differs():
    a = _render(_lean_cfg(pivot_x=0.5, pivot_y=0.5), value=12.0)
    b = _render(_lean_cfg(pivot_x=0.5, pivot_y=1.0), value=12.0)
    assert a.size == b.size
    assert ImageChops.difference(a, b).getbbox() is not None


def test_center_pivot_keeps_bbox_center_invariant():
    # rotating around the centre: the graphic bbox centre stays at the widget
    # centre for any angle (graphic-only render).
    img0 = _render(_graphic_only_cfg(pivot_x=0.5, pivot_y=0.5), value=0.0)
    img1 = _render(_graphic_only_cfg(pivot_x=0.5, pivot_y=0.5), value=20.0)
    c0 = _alpha_bbox_center(img0)
    c1 = _alpha_bbox_center(img1)
    assert c0 is not None and c1 is not None
    assert abs(c0[0] - img0.width / 2.0) < 3
    assert abs(c0[1] - c1[1]) < 3  # vertical centre invariant under roll


def test_bottom_pivot_bbox_center_shifts_with_angle():
    # off-centre pivot: rotating the graphic moves its bbox centre (the pivot
    # stays fixed while the content swings), unlike the centre pivot above.
    img0 = _render(_graphic_only_cfg(pivot_x=0.5, pivot_y=1.0), value=0.0)
    img1 = _render(_graphic_only_cfg(pivot_x=0.5, pivot_y=1.0), value=22.0)
    c0 = _alpha_bbox_center(img0)
    c1 = _alpha_bbox_center(img1)
    assert c0 is not None and c1 is not None
    assert abs(c0[1] - c1[1]) > 2  # bbox centre moved -> real off-centre pivot


def _alpha_bbox_center(img):
    arr = np.asarray(img)
    ys, xs = np.where(arr[:, :, 3] > 30)
    if not len(ys):
        return None
    return (xs.mean(), ys.mean())


# ---------------------------------------------------------------------------
# TEST 3 — PREVIEW / FINAL PARITY (same pivot)
# ---------------------------------------------------------------------------

def test_preview_final_same_pivot():
    layout = {"global": {}, "indicators": {"lean_indicator": _lean_cfg(
        pivot_x=0.5, pivot_y=1.0, source="gyro", axis="x",
    )}}
    extra = {"lean_indicator": (12.0, "°", "PRZECHYŁ")}
    bf, bp = {}, {}
    img_f = compose_overlay(1280, 720, layout, "", "", "", 0.0, 0.0, 0.0,
                            extra_indicators=extra, _bboxes=bf,
                            fast_preview=False, reuse_canvas=False)
    img_p = compose_overlay(1280, 720, layout, "", "", "", 0.0, 0.0, 0.0,
                            extra_indicators=extra, _bboxes=bp,
                            fast_preview=True, reuse_canvas=False)
    b = bf.get("lean_indicator")
    cf = img_f.crop((b[0], b[1], b[0] + b[2], b[1] + b[3]))
    cp = img_p.crop((b[0], b[1], b[0] + b[2], b[1] + b[3]))
    assert ImageChops.difference(cf, cp).getbbox() is None


# ---------------------------------------------------------------------------
# TEST 4 — LEGACY CONFIG without pivot fields
# ---------------------------------------------------------------------------

def test_legacy_config_without_pivot_renders():
    cfg = _lean_cfg()
    del cfg["pivot_x"]
    del cfg["pivot_y"]
    img = _render(cfg, value=8.0)
    assert img is not None and img.getbbox() is not None
    # defaults applied: bottom-centre
    px, py = _graphic_pivot(cfg, 200, 100)
    assert px == pytest.approx(100.0)
    assert py == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# TEST 5 — PIVOT change does not break position / scale / text
# ---------------------------------------------------------------------------

def test_pivot_change_keeps_widget_size_and_value_text():
    a = _render(_lean_cfg(pivot_x=0.5, pivot_y=0.5), value=15.0)
    b = _render(_lean_cfg(pivot_x=0.5, pivot_y=1.0), value=15.0)
    c = _render(_lean_cfg(pivot_x=0.25, pivot_y=0.9), value=15.0)
    assert a.size == b.size == c.size  # widget size unchanged
    # value text row (below the graphic) stays identical across pivots
    row_a = _value_row(a)
    row_b = _value_row(b)
    row_c = _value_row(c)
    assert row_a == row_b == row_c


def _value_row(img):
    """Extract the readout row (bottom strip) as a byte signature."""
    h = img.height
    strip = img.crop((0, int(h * 0.72), img.width, h))
    return strip.tobytes()
