"""ETAP 11B — unified BAR Ruler + orientation + units + adaptive major step.

Regression contract (task Parts A–G):

- Ruler and Slope are ONE indicator: ``bar_style="ruler"`` + ``orientation``
  (horizontal | vertical).  Legacy ``bar_style="slope"`` normalises in-memory.
- Text is ALWAYS horizontal (the raster is never rotated).
- Distance uses ONE m→km conversion (normalised at the display boundary).
- Explicit AUTO major tick (nice step 1/2/5×10^n), on top of the 10Y COUNT/STEP
  contract; ``minor_ticks`` stays user-controlled.
- Preview == Final render marker fraction/visibility.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageChops

from src.indicators.bar import (
    _fraction,
    _nice_step,
    _normalize_slope_cfg,
    _render_bar_indicator,
    _render_ruler_vertical,
    _resolve_major_tick_plan,
)
from src.indicators.compositor import compose_overlay

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**over):
    cfg = {
        "enabled": True, "form": "bar", "bar_style": "ruler",
        "label": "TEST", "unit": "km", "source": "gpmf",
        "x": 50.0, "y": 50.0, "rotation": 0, "size": 20.0,
        "font_size": 1.2, "thickness": 2,
        "min_val": 0.0, "max_val": 10.0,
        "major_ticks": 5, "minor_ticks": 1,
        "show_value": True, "show_label": True, "show_range_labels": True,
        "show_mid_label": True, "range_units": True, "decimals": 1,
        "marker_color": "#FFD42A", "marker_border_color": "#FFFFFF",
        "marker_size": 6, "tick_color": "#F6F6F6", "tick_profile": "default",
    }
    cfg.update(over)
    return cfg


def _render(cfg, value, canvas=(1280, 720), formatted=None):
    w, h = canvas
    return _render_bar_indicator(
        w, h, {"global": {}, "indicators": {"probe": cfg}}, "",
        "probe", value, cfg.get("unit", ""), cfg.get("label", "TEST"), cfg,
        min(w, h), 2, max(8, round(20.0 / 100.0 * h)), None,
        float(cfg["min_val"]), float(cfg["max_val"]),
        int(cfg.get("ticks", 0)), int(cfg.get("thickness", 2)),
        round(cfg.get("size", 20.0) / 100.0 * w), 1,
        formatted_val=formatted,
    )[0]


def _marker(img):
    """Yellow (#FFD42A) marker pixels -> (mean_x, mean_y, count)."""
    arr = np.asarray(img)
    mask = (arr[:, :, 0] > 200) & (arr[:, :, 1] > 150) & (
        arr[:, :, 2] < 100) & (arr[:, :, 3] > 150)
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    return float(xs.mean()), float(ys.mean()), int(len(xs))


def _text_bbox(img):
    arr = np.asarray(img)
    ys, xs = np.where(arr[:, :, 3] > 30)
    if not len(ys):
        return None
    return xs.min(), ys.min(), xs.max() - xs.min(), ys.max() - ys.min()


# ---------------------------------------------------------------------------
# TEST 1 — SLOPE MIGRATION
# ---------------------------------------------------------------------------

def test_slope_style_normalises_to_ruler_vertical_in_memory():
    # A real legacy slope preset has NO ruler COUNT keys (major_ticks/
    # minor_ticks) — it uses value-based major_tick/minor_tick.
    legacy = _cfg(bar_style="slope", field="slope", unit="%",
                  min_val=-20.0, max_val=20.0, major_tick=5.0, minor_tick=1.0,
                  show_tick_labels=None, tick_label_signed=None, marker_style=None)
    del legacy["major_ticks"]
    del legacy["minor_ticks"]
    before = deepcopy(legacy)
    norm = _normalize_slope_cfg(legacy)
    # Original config is NEVER mutated (TEST 16, A5).
    assert legacy == before
    # style=slope -> ruler + orientation=vertical
    assert norm["bar_style"] == "ruler"
    assert norm["orientation"] == "vertical"
    assert norm["_legacy_slope"] is True
    # value-based ticks map onto the ruler STEP contract
    assert norm["major_step"] == 5.0
    assert norm["minor_ticks"] == 5
    # slope-specific visuals preserved as options
    assert norm.get("show_tick_labels", True) is True
    assert norm.get("tick_label_signed", True) is True
    assert norm.get("marker_style", "line") == "line"
    assert norm["show_range_labels"] is False


def test_slope_render_still_works_and_is_vertical():
    # A legacy bar_style=slope config renders through the unified path.
    img = _render(_cfg(bar_style="slope", unit="%", min_val=-20.0, max_val=20.0,
                       major_tick=5.0, minor_tick=1.0), 0.0, formatted="+0.0%")
    assert img is not None and img.getbbox() is not None
    # The vertical ruler is taller than wide (axis is vertical).
    assert img.height > img.width


def test_slope_missing_value_skips_marker():
    img = _render(_cfg(bar_style="slope", unit="%", min_val=-20.0, max_val=20.0,
                       major_tick=5.0, minor_tick=1.0, _slope_missing=True),
                  0.0, formatted="--%")
    assert _marker(img) is None


# ---------------------------------------------------------------------------
# TEST 2 / TEST 3 — HORIZONTAL vs VERTICAL (same scale contract)
# ---------------------------------------------------------------------------

def test_horizontal_ruler_renders_scale_and_marker():
    img = _render(_cfg(bar_style="ruler", orientation="horizontal"), 5.0)
    m = _marker(img)
    assert m is not None
    x, y, count = m
    # value 5 on 0..10 -> 50% -> marker near horizontal centre
    assert 0.35 * img.width < x < 0.65 * img.width


def test_vertical_uses_same_fraction_contract_only_geometry_changes():
    # Same config, only orientation changes -> same tick plan and same fraction.
    cfg_h = _cfg(orientation="horizontal", min_val=0.0, max_val=10.0)
    cfg_v = _cfg(orientation="vertical", min_val=0.0, max_val=10.0)
    plan_h = _resolve_major_tick_plan(cfg_h, 0.0, 10.0, 0)
    plan_v = _resolve_major_tick_plan(cfg_v, 0.0, 10.0, 0)
    assert plan_h == plan_v
    assert _fraction(5.0, 0.0, 10.0) == pytest.approx(0.5)

    img_v = _render(cfg_v, 5.0)
    m = _marker(img_v)
    assert m is not None
    x, y, count = m
    # value 5 -> 50% -> marker near vertical centre (fraction identical, Y axis)
    assert 0.35 * img_v.height < y < 0.65 * img_v.height


def test_vertical_min_bottom_max_top():
    img_hi = _render(_cfg(orientation="vertical", min_val=-20.0, max_val=20.0), 20.0)
    img_lo = _render(_cfg(orientation="vertical", min_val=-20.0, max_val=20.0), -20.0)
    m_hi = _marker(img_hi)
    m_lo = _marker(img_lo)
    assert m_hi is not None and m_lo is not None
    # max -> TOP (smaller y), min -> BOTTOM (larger y)
    assert m_hi[1] < m_lo[1]


# ---------------------------------------------------------------------------
# TEST 4 — TEXT NOT ROTATED
# ---------------------------------------------------------------------------

def test_vertical_text_is_never_rotated():
    # Only the value text is on the right side (no title/range/tick labels), so
    # the rightmost band is the value glyphs.  If the whole raster were rotated
    # 90° the value text would become a tall, narrow vertical strip (h > w);
    # here it must stay wide and short (horizontal).
    img = _render(_cfg(orientation="vertical", min_val=0.0, max_val=10.0,
                       show_value=True, show_label=False, show_range_labels=False,
                       show_mid_label=False, marker_style="dot"), 5.0,
                  formatted="5.0 km")
    arr = np.asarray(img)
    ys, xs = np.where(arr[:, :, 3] > 30)
    assert len(xs) > 0
    right = xs > 0.6 * img.width
    assert right.any(), "value text expected on the right side of the track"
    xs_r, ys_r = xs[right], ys[right]
    w = int(xs_r.max() - xs_r.min())
    h = int(ys_r.max() - ys_r.min())
    # horizontal glyphs: width clearly exceeds height (not a 90° column)
    assert w > h * 1.5
    # the value text is a compact band, not a full-height strip
    assert h < 0.2 * img.height


# ---------------------------------------------------------------------------
# TEST 5 / TEST 6 — DISTANCE UNIT + MARKER (m -> km exactly once)
# ---------------------------------------------------------------------------

def test_distance_extra_indicator_normalised_meters_to_km():
    """fit_distance_text arrives via extra_indicators as raw METERS -> km."""
    captured = {}

    def fake_render(*args, **kwargs):
        captured["value"] = args[5]
        captured["unit"] = args[6]
        captured["min"] = kwargs["cfg_override"].get("min_val")
        captured["max"] = kwargs["cfg_override"].get("max_val")
        return Image.new("RGBA", (4, 4), (255, 255, 255, 255)), 100, 100, None

    import src.indicators.compositor as comp
    monkey = __import__("pytest").MonkeyPatch()
    monkey.setattr(comp, "render_value_indicator", fake_render)
    layout = {"global": {}, "indicators": {"fit_distance_text": _cfg(
        label="FIT DIST", unit="km", min_val=0.0, max_val=20.0, source="fit",
    )}}
    try:
        compose_overlay(
            1920, 1080, layout, "", "", "", 0.0, 0.0, 2955.5,
            indicator_values={},
            extra_indicators={"fit_distance_text": (10000.0, "km", "FIT DIST")},
            fast_preview=True, reuse_canvas=False,
        )
    finally:
        monkey.undo()
    assert captured["value"] == pytest.approx(10.0)   # 10000 m -> 10 km
    assert captured["unit"] == "km"
    assert captured["max"] == 20.0


def test_distance_marker_fraction_from_normalised_value():
    # range 0..20 km, raw 10000 m -> display 10 km -> fraction 0.5
    img = _render(_cfg(orientation="horizontal", min_val=0.0, max_val=20.0), 10.0)
    m = _marker(img)
    assert m is not None
    assert 0.35 * img.width < m[0] < 0.65 * img.width


# ---------------------------------------------------------------------------
# TEST 7 / TEST 8 — PREVIEW / FINAL MARKER PARITY + VISIBILITY
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [0.0, 5.0, 10.0])
def test_preview_final_marker_parity_and_visible(value):
    layout = {"global": {}, "indicators": {"dist_visual": _cfg(
        label="DISTANCE", unit="km", min_val=0.0, max_val=10.0, source="gpmf",
    )}}
    bboxes = {}
    img_final = compose_overlay(
        1920, 1080, layout, "", "", "", 0.0, value * 1000.0, 10000.0,
        indicator_values={"dist_visual": value * 1000.0},
        _bboxes=bboxes, fast_preview=False, reuse_canvas=False,
    )
    b = bboxes.get("dist_visual")
    assert b is not None
    crop = img_final.crop((b[0], b[1], b[0] + b[2], b[1] + b[3]))
    # final marker VISIBLE (TEST 8)
    m_final = _marker(crop)
    assert m_final is not None

    bboxes_p = {}
    img_preview = compose_overlay(
        1920, 1080, layout, "", "", "", 0.0, value * 1000.0, 10000.0,
        indicator_values={"dist_visual": value * 1000.0},
        _bboxes=bboxes_p, fast_preview=True, reuse_canvas=False,
    )
    b_p = bboxes_p["dist_visual"]
    crop_p = img_preview.crop((b_p[0], b_p[1], b_p[0] + b_p[2], b_p[1] + b_p[3]))
    m_prev = _marker(crop_p)
    assert m_prev is not None
    # identical widget -> identical marker x (preview == final)
    assert m_prev[0] == pytest.approx(m_final[0], abs=2.0)
    assert m_prev[2] == m_final[2]


# ---------------------------------------------------------------------------
# TEST 9–12 — ADAPTIVE NICE STEP
# ---------------------------------------------------------------------------

def test_nice_step_distance_10km():
    assert _nice_step(10.0) == 1.0
    divs = round(10.0 / _nice_step(10.0))
    assert 5 <= divs <= 12


def test_nice_step_cadence_100rpm():
    step = _nice_step(100.0)
    assert 5 <= round(100.0 / step) <= 12
    # natural cadence step ~10 rpm
    assert step in (5.0, 10.0)


def test_nice_step_temperature_small_range():
    assert _nice_step(10.0) == 1.0       # 0..10 °C -> 1 °C
    step = _nice_step(30.0)              # 0..30 °C -> 2 or 5 °C
    assert 5 <= round(30.0 / step) <= 12


def test_nice_step_large_range_avoids_hundreds_of_ticks():
    for rng in (500.0, 1000.0, 5000.0, 120.0):
        step = _nice_step(rng)
        divs = round(rng / step)
        assert 4 <= divs <= 14, f"range {rng} step {step} divs {divs}"
        # step is a 1/2/5×10^n value
        assert step in {1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000}


def test_auto_mode_uses_nice_step_in_renderer():
    cfg = _cfg(major_tick_mode="auto", min_val=0.0, max_val=100.0)
    mode, step, divs, minor = _resolve_major_tick_plan(cfg, 0.0, 100.0, 0)
    assert mode == "auto"
    assert step == pytest.approx(10.0)
    assert divs == 10


# ---------------------------------------------------------------------------
# TEST 13 / TEST 14 — MANUAL STEP + COUNT still per 10Y
# ---------------------------------------------------------------------------

def test_manual_step_priority_legacy():
    cfg = _cfg(min_val=0.0, max_val=10.0, major_step=2.0)  # no mode -> legacy STEP
    mode, step, divs, minor = _resolve_major_tick_plan(cfg, 0.0, 10.0, 0)
    assert mode == "step"
    assert step == pytest.approx(2.0)
    assert divs == 5


def test_count_mode_respects_major_ticks():
    for n in (4, 8, 12):
        cfg = _cfg(major_tick_mode="count", major_ticks=n, major_step=0.0,
                   min_val=0.0, max_val=10.0)
        mode, step, divs, minor = _resolve_major_tick_plan(cfg, 0.0, 10.0, 0)
        assert mode == "count"
        assert step is None
        assert divs == n


def test_count_and_step_modes_render_differently():
    img_count = _render(_cfg(major_tick_mode="count", major_ticks=5, min_val=0.0, max_val=10.0), 5.0)
    img_step = _render(_cfg(major_tick_mode="step", major_step=1.0, min_val=0.0, max_val=10.0), 5.0)
    assert ImageChops.difference(img_count, img_step).getbbox() is not None


# ---------------------------------------------------------------------------
# TEST 15 — MINOR TICKS in all modes / orientations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
@pytest.mark.parametrize("mode_kwargs", [
    {"major_tick_mode": "count", "major_ticks": 5},
    {"major_tick_mode": "step", "major_step": 2.0},
    {"major_tick_mode": "auto"},
])
def test_minor_ticks_respected_everywhere(orientation, mode_kwargs):
    base = _cfg(orientation=orientation, min_val=0.0, max_val=100.0, **mode_kwargs)
    img5 = _render(dict(base, minor_ticks=5), 50.0)
    img9 = _render(dict(base, minor_ticks=9), 50.0)
    assert ImageChops.difference(img5, img9).getbbox() is not None
    # minor count reflected in the plan (with the same config that was rendered)
    _, _, _, minor = _resolve_major_tick_plan(dict(base, minor_ticks=5), 0.0, 100.0, 0)
    assert minor == 5


# ---------------------------------------------------------------------------
# TEST 16 — CONFIG IMMUTABILITY
# ---------------------------------------------------------------------------

def test_renderer_does_not_mutate_config():
    cfg = _cfg(bar_style="slope", unit="%", min_val=-20.0, max_val=20.0,
               major_tick=5.0, minor_tick=1.0)
    before = deepcopy(cfg)
    _render(cfg, 3.0, formatted="+3.0%")
    assert cfg == before
    # vertical ruler also immutable
    cfg2 = _cfg(orientation="vertical", min_val=0.0, max_val=10.0)
    before2 = deepcopy(cfg2)
    _render(cfg2, 5.0)
    assert cfg2 == before2
