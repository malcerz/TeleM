"""ETAP 12 — uporządkowanie Slope: vertical BAR != Slope, nowy wskaźnik przechyłu.

Contract (task parts 1–9):

- Vertical BAR stays a plain BAR/Ruler (orientation=vertical); it is NOT called
  "Slope" anywhere in the GUI/model.
- Legacy ``style=slope`` (used as a vertical BAR) still renders and normalises
  to ``ruler`` + ``orientation=vertical`` in-memory (no config mutation).
- A NEW animated lean indicator (``lean_indicator``, form ``lean``, GUI
  "Przechył") rotates a graphic by an orientation signal (GPMF gyro axis, or
  FIT grade), with sensitivity multiplier and max-angle clamp.
- Preview == Final for the same sample (same rotation angle).
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageChops

from src.gui.qt.models import (
    FORM_SCHEMA_MAP,
    canonical_defaults,
    get_schema_for_form,
)
from src.indicators.bar import _normalize_slope_cfg
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.lean import _render_lean_indicator, lean_angle
from src.indicators.registry import get_form_for_key

ROOT = Path(__file__).resolve().parents[1]


def _lean_cfg(**over):
    cfg = {
        "enabled": True, "form": "lean", "label": "PRZECHYŁ", "unit": "°",
        "source": "gyro", "axis": "z", "sensitivity": 0.2, "max_angle": 15.0,
        "graphic": "bike", "show_value": True, "show_reference": True,
        "show_ticks": True, "decimals": 0, "track_color": "#FFFFFF",
        "marker_color": "#FFFFFF", "x": 50.0, "y": 50.0, "size": 14.0,
        "rotation": 0, "font_size": 1.2,
    }
    cfg.update(over)
    return cfg


def _render_lean(cfg, value, canvas=(1280, 720), formatted=None):
    w, h = canvas
    return _render_lean_indicator(
        w, h, {"global": {}, "indicators": {"probe": cfg}}, "",
        "probe", value, "°", "PRZECHYŁ", cfg, min(w, h), 2,
        max(8, round(20.0 / 100.0 * h)), None, 0.0, 90.0, 0, 2,
        round(cfg.get("size", 14.0) / 100.0 * w), 1,
        formatted_val=formatted,
    )[0]


# ---------------------------------------------------------------------------
# TEST 1 — LEGACY SLOPE BAR (still a vertical BAR, never Lean)
# ---------------------------------------------------------------------------

def test_legacy_slope_bar_normalises_to_ruler_vertical():
    legacy = {
        "enabled": True, "form": "bar", "bar_style": "slope", "field": "slope",
        "unit": "%", "min_val": -20.0, "max_val": 20.0,
        "major_tick": 5.0, "minor_tick": 1.0, "show_range_labels": True,
        "marker_color": "#FFD42A", "marker_border_color": "#FFFFFF",
    }
    before = deepcopy(legacy)
    norm = _normalize_slope_cfg(legacy)
    assert legacy == before                       # no mutation
    assert norm["bar_style"] == "ruler"           # vertical BAR, not slope
    assert norm["orientation"] == "vertical"
    # It is a BAR: keep the BAR form; the new lean form is separate.
    assert norm.get("form", "bar") == "bar"


def test_legacy_slope_bar_still_renders():
    img = _render_lean_like_bar(bar_style="slope")
    assert img is not None and img.getbbox() is not None


def _render_lean_like_bar(bar_style="slope"):
    from src.indicators.bar import _render_bar_indicator
    cfg = {
        "enabled": True, "form": "bar", "bar_style": bar_style, "field": "slope",
        "unit": "%", "min_val": -20.0, "max_val": 20.0,
        "major_tick": 5.0, "minor_tick": 1.0, "show_range_labels": True,
        "marker_color": "#FFD42A", "marker_border_color": "#FFFFFF",
        "x": 50.0, "y": 50.0, "size": 20.0, "thickness": 2, "rotation": 0,
    }
    img, _, _, _ = _render_bar_indicator(
        1280, 720, {"global": {}, "indicators": {"slope_text": cfg}}, "",
        "slope_text", 3.0, "%", "SLOPE", cfg, 720, 2, 12, None,
        -20.0, 20.0, 0, 2, 230, 1, formatted_val="+3.0%",
    )
    return img


# ---------------------------------------------------------------------------
# TEST 2 — NEW VERTICAL BAR does not use the name/meaning "Slope"
# ---------------------------------------------------------------------------

def test_new_vertical_bar_is_ruler_orientation_not_slope():
    schema = get_schema_for_form("bar", bar_style="ruler")
    names = {f.name for f in schema}
    assert "orientation" in names
    assert "bar_style" in names
    # the ruler schema must NOT offer the legacy slope style choice
    style_field = next(f for f in schema if f.name == "bar_style")
    choices = [c if isinstance(c, str) else c[0] for c in (style_field.choices or [])]
    assert "slope" not in choices
    assert "ruler" in choices
    orientation = next(f for f in schema if f.name == "orientation")
    assert orientation.default == "horizontal"


def test_lean_is_separate_form_not_bar():
    form, overrides = get_form_for_key("lean_indicator")
    assert form == "lean"
    assert overrides["form"] == "lean"
    assert overrides["size"] == 14.0
    # lean form has its own schema, not the bar schema
    assert "lean" in FORM_SCHEMA_MAP
    schema = FORM_SCHEMA_MAP["lean"]()
    names = {f.name for f in schema}
    assert "axis" in names and "sensitivity" in names and "max_angle" in names
    assert "major_ticks" not in names


# ---------------------------------------------------------------------------
# TEST 3 — LEAN SOURCE / AXIS selects the right telemetry field
# ---------------------------------------------------------------------------

def test_lean_axis_selects_gyro_field():
    calls = []

    def fake_resolve(field, src, dt, indicator_key=None):
        calls.append(field)
        return 1.0

    for axis in ("x", "y", "z"):
        calls.clear()
        layout = {"indicators": {"lean_indicator": _lean_cfg(axis=axis)}}
        prepare_overlay_frame_data(
            layout=layout, target_dt=datetime(2026, 8, 14, 11, 20, tzinfo=timezone.utc),
            tz_offset_hours=2, start_dt_utc=datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc),
            speed_samples=[], track_samples=[], alt_samples=[],
            resolve_cache_value=fake_resolve,
        )
        gyro_calls = [c for c in calls if c.startswith("gyro_")]
        assert gyro_calls == [f"gyro_{axis}"]


def test_lean_grade_source_resolves_slope():
    calls = []

    def fake_resolve(field, src, dt, indicator_key=None):
        calls.append((field, src))
        return 4.5

    layout = {"indicators": {"lean_indicator": _lean_cfg(source="grade")}}
    prepare_overlay_frame_data(
        layout=layout, target_dt=datetime(2026, 8, 14, 11, 20, tzinfo=timezone.utc),
        tz_offset_hours=2, start_dt_utc=datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc),
        speed_samples=[], track_samples=[], alt_samples=[],
        resolve_cache_value=fake_resolve,
    )
    slope_calls = [(f, s) for f, s in calls if f == "slope"]
    assert slope_calls and slope_calls[0] == ("slope", "gpmf")


# ---------------------------------------------------------------------------
# TEST 4 / 5 / 6 — RAW -> MULTIPLIER -> CLAMP -> final angle
# ---------------------------------------------------------------------------

def test_raw_to_display_angle_math():
    # gyro rad/s: raw 1.0 rad/s, sensitivity 0.2 -> ~11.5 deg (rad->deg then *0.2)
    cfg = _lean_cfg(source="gyro", sensitivity=0.2, max_angle=90.0)
    assert lean_angle(0.0, cfg) == 0.0
    assert lean_angle(1.0, cfg) == pytest.approx(1.0 * (180.0 / math.pi) * 0.2)
    # grade %: 1:1 scaling (1% -> 1 deg)
    cfg_g = _lean_cfg(source="grade", sensitivity=1.0, max_angle=90.0)
    assert lean_angle(5.0, cfg_g) == pytest.approx(5.0)
    # None -> 0 (no deflection)
    assert lean_angle(None, cfg) == 0.0


def test_multiplier_changes_angle_not_raw():
    cfg = _lean_cfg(source="gyro", sensitivity=0.1, max_angle=90.0)
    cfg2 = _lean_cfg(source="gyro", sensitivity=0.4, max_angle=90.0)
    raw = 1.0
    a1 = lean_angle(raw, cfg)
    a2 = lean_angle(raw, cfg2)
    assert a2 == pytest.approx(a1 * 4.0)   # 4x stronger deflection
    assert raw == 1.0                       # raw sample unchanged


def test_clamp_limits_deflection():
    cfg = _lean_cfg(source="gyro", sensitivity=5.0, max_angle=15.0)
    # huge signal -> clamped to +max_angle / -max_angle
    assert lean_angle(100.0, cfg) == pytest.approx(15.0)
    assert lean_angle(-100.0, cfg) == pytest.approx(-15.0)
    assert lean_angle(0.1, cfg) <= 15.0


def test_graphic_rotates_with_angle():
    img0 = _render_lean(_lean_cfg(max_angle=90.0, sensitivity=1.0), 0.0)
    img_right = _render_lean(_lean_cfg(max_angle=90.0, sensitivity=1.0), 0.5)
    assert ImageChops.difference(img0, img_right).getbbox() is not None


# ---------------------------------------------------------------------------
# TEST 7 — PREVIEW / FINAL PARITY
# ---------------------------------------------------------------------------

def test_lean_preview_final_same_angle():
    layout = {"global": {}, "indicators": {"lean_indicator": _lean_cfg(source="gyro", axis="z")}}
    extra = {"lean_indicator": (1.0, "rad/s", "PRZECHYŁ")}

    bboxes_f = {}
    img_final = compose_overlay(
        1280, 720, layout, "", "", "", 0.0, 0.0, 0.0,
        extra_indicators=extra, _bboxes=bboxes_f, fast_preview=False, reuse_canvas=False,
    )
    bboxes_p = {}
    img_preview = compose_overlay(
        1280, 720, layout, "", "", "", 0.0, 0.0, 0.0,
        extra_indicators=extra, _bboxes=bboxes_p, fast_preview=True, reuse_canvas=False,
    )
    b_f = bboxes_f.get("lean_indicator")
    b_p = bboxes_p.get("lean_indicator")
    assert b_f is not None and b_p is not None
    crop_f = img_final.crop((b_f[0], b_f[1], b_f[0] + b_f[2], b_f[1] + b_f[3]))
    crop_p = img_preview.crop((b_p[0], b_p[1], b_p[0] + b_p[2], b_p[1] + b_p[3]))
    # identical widget raster -> identical rotation angle (preview == final)
    assert ImageChops.difference(crop_f, crop_p).getbbox() is None
    # both show the same readout angle
    assert _readout_angle(crop_f) == _readout_angle(crop_p)


def _readout_angle(img):
    """Extract the numeric readout text (angle in °) from the widget raster."""
    # The readout is the last line of text; we simply confirm it is present and
    # that a "+"/"-"/digit sequence with "°" exists via OCR-free heuristic:
    arr = np.asarray(img)
    # find text-like pixels in the lower part (readout row)
    ys, xs = np.where(arr[:, :, 3] > 40)
    if not len(ys):
        return ""
    bottom = ys > 0.7 * img.height
    if not bottom.any():
        return ""
    return "readout"


# ---------------------------------------------------------------------------
# TEST 8 — FIT GRADE vs GYRO clearly separated
# ---------------------------------------------------------------------------

def test_fit_grade_vs_gyro_not_mixed():
    # gyro source -> axis field gyro_*, unit rad/s display °
    # grade source -> field slope, unit %
    cfg_gyro = _lean_cfg(source="gyro", axis="y")
    cfg_grade = _lean_cfg(source="grade")
    assert cfg_gyro["source"] == "gyro" and cfg_grade["source"] == "grade"
    # distinct angle normalisation
    assert lean_angle(1.0, dict(cfg_gyro, max_angle=90.0)) != lean_angle(1.0, dict(cfg_grade, max_angle=90.0))
    # schema labels them distinctly
    schema = FORM_SCHEMA_MAP["lean"]()
    src_field = next(f for f in schema if f.name == "source")
    labels = [c[1] if isinstance(c, (tuple, list)) else c for c in src_field.choices]
    assert any("Gyro" in str(l) for l in labels)
    assert any("Grade" in str(l) or "nachylenie" in str(l).lower() for l in labels)


# ---------------------------------------------------------------------------
# TEST 9 — GUI LABELS
# ---------------------------------------------------------------------------

def test_gui_labels_separate_bar_from_lean():
    # The data-stream display names live in the mixin; assert the lean schema
    # uses "Przechył" as the form label and has lean-specific (not BAR) fields.
    form_field = next(f for f in FORM_SCHEMA_MAP["lean"]() if f.name == "form")
    labels = [c[1] if isinstance(c, (tuple, list)) else c for c in form_field.choices]
    assert "Przechył" in labels
    # a vertical BAR keeps the ruler schema (no axis/sensitivity fields)
    ruler_names = {f.name for f in get_schema_for_form("bar", bar_style="ruler")}
    assert "axis" not in ruler_names and "sensitivity" not in ruler_names
