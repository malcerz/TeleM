"""Tests for src/indicators/gauge.py — Gauge-form indicator rendering.

Covers:
- "nice" (round) major tick labels across common max_val settings,
- needle geometry independent of the supersampling factor (regression),
- needle deflection vs the rounded display range,
- centre marker toggle,
- Właściwości schema exposing only controls the renderer actually uses.
"""

from __future__ import annotations

import pytest

from src.indicators.gauge import _gauge_ticks, _render_gauge_indicator


def _render(cfg, value=0.0, ss=1, size_px=100):
    """Render a gauge with defaults + the given overrides; return the PIL Image."""
    full = {
        "size": 0.1, "x": 50, "y": 50,
        "start_angle": 180, "sweep_angle": 180,
        "needle_length": 1.1, "needle_width": 4,
        "needle_color": "#DC3232", "show_value": False,
        "text_color": "#FFFFFF", "min_val": 0, "max_val": 180, "ticks": 10,
        "thickness": 1,
    }
    full.update(cfg)
    img, _, _, _ = _render_gauge_indicator(
        1920, 1080, {"indicators": {"g": full}}, "",
        "g", value, "km/h", "",
        full, 1080, 3, 16, None, 0, 180, 10, 20, size_px, ss,
    )
    return img


def _is_red(pixel):
    return pixel[0] > 200 and pixel[1] < 100 and pixel[2] < 100 and pixel[3] > 200


def _needle_extent_x(img):
    """Return (min_x, max_x) of red (needle) pixels, or (None, None) if absent."""
    px = img.load()
    xs = [x for y in range(img.size[1]) for x in range(img.size[0])
          if _is_red(px[x, y])]
    return (min(xs), max(xs)) if xs else (None, None)


# ── Scale / tick labels ─────────────────────────────────────────────────────

def test_gauge_ticks_round_labels():
    """Major tick labels must be round for common speedometer maxima."""
    for raw_max in (40, 60, 100, 120, 180, 200, 240, 300, 359):
        dmn, dmx, step, majors, sub, total = _gauge_ticks(0.0, float(raw_max), 10)
        assert dmx > dmn
        assert majors >= 1
        assert total == majors * sub
        # display range is an exact multiple of the step → even label spacing
        assert dmx - dmn == pytest.approx(majors * step)
        # every major label is a round number (multiple of step above display_min)
        for k in range(majors + 1):
            assert (dmn + k * step) % step == pytest.approx(0.0)


def test_gauge_ticks_reports_sane_values():
    """Known scale: request 0..180 → display 0..200 with step 50 (4 majors)."""
    dmn, dmx, step, majors, sub, total = _gauge_ticks(0.0, 180.0, 10)
    assert (dmn, dmx, step, majors) == (0.0, 200.0, 50.0, 4)
    assert total == 40


def test_gauge_ticks_respects_min_val():
    """Non-zero min_val keeps a round display range."""
    dmn, dmx, step, majors, sub, total = _gauge_ticks(-10.0, 40.0, 10)
    assert dmn == -10.0
    assert dmx == 40.0
    assert step == 10.0
    assert majors == 5
    assert [dmn + k * step for k in range(majors + 1)] == \
        [-10.0, 0.0, 10.0, 20.0, 30.0, 40.0]


# ── Needle supersampling (regression) ───────────────────────────────────────

def test_gauge_needle_length_independent_of_supersample():
    """The needle must keep the same output length regardless of ss (not clip)."""
    min1, _ = _needle_extent_x(_render({}, value=0.0, ss=1))
    min2, _ = _needle_extent_x(_render({}, value=0.0, ss=2))
    min3, _ = _needle_extent_x(_render({}, value=0.0, ss=3))
    assert min1 is not None and min2 is not None and min3 is not None
    # ss>1 must never push the needle off the image (the old bug clipped at 0)
    assert min2 > 0
    assert min3 > 0
    # same physical length in output pixels regardless of supersampling
    assert abs(min2 - min1) <= 2
    assert abs(min3 - min1) <= 2


# ── Needle deflection vs display range ──────────────────────────────────────

def test_gauge_needle_full_deflection_at_display_max():
    """value == display_max sweeps the needle to the end of the arc."""
    # max_val 180 → display range 0..200
    _, max_full = _needle_extent_x(_render({"max_val": 180}, value=200.0))
    _, max_half = _needle_extent_x(_render({"max_val": 180}, value=100.0))
    assert max_full > 220   # swept to the right (end angle 360°)
    assert max_half < 160   # halfway → pointing down, not right


# ── Centre marker ───────────────────────────────────────────────────────────

def test_gauge_marker_toggle():
    """show_marker controls whether the centre dot is drawn."""
    img_on = _render({"show_marker": True, "marker_size": 6,
                      "marker_color": "#FFFFFF"}, value=0.0)
    img_off = _render({"show_marker": False, "marker_size": 6,
                       "marker_color": "#FFFFFF"}, value=0.0)
    cx = img_on.size[0] // 2
    cy = img_on.size[1] // 2
    # (cx+3, cy) is inside the marker (r=6) but outside the needle (points left)
    px_on = img_on.getpixel((cx + 3, cy))
    px_off = img_off.getpixel((cx + 3, cy))
    assert px_on[0] > 200 and px_on[3] > 200   # white marker dot present
    assert px_off[3] < 128                      # no marker → transparent


# ── Właściwości schema ─────────────────────────────────────────────────────

def test_gauge_schema_exposes_only_used_fields():
    """The Właściwości panel must not offer controls the renderer ignores."""
    from src.gui.qt.models import gauge_indicator_fields
    names = {f.name for f in gauge_indicator_fields()}
    for dead in ("show_bar", "bar_width", "label_count", "label_font_size",
                 "label_units", "show_average"):
        assert dead not in names
    for used in ("start_angle", "sweep_angle", "needle_length", "needle_width",
                 "needle_color", "show_marker", "marker_size", "marker_color",
                 "min_val", "max_val", "ticks", "thickness", "show_value"):
        assert used in names


def test_gauge_schema_text_offset_range_is_fractional():
    """text_offset_x/y are fractional multipliers — range must stay small."""
    from src.gui.qt.models import gauge_indicator_fields
    fields = {f.name: f for f in gauge_indicator_fields()}
    for name in ("text_offset_x", "text_offset_y"):
        f = fields[name]
        assert f.min_val >= -1.0
        assert f.max_val <= 1.0


# ── Centre value vs label (regression) ─────────────────────────────────────

def test_gauge_centre_value_respects_show_value_and_color():
    """speed_visual must show the value (not the label) and honour show_value."""
    def render_centre(show_value, formatted_val):
        cfg = {
            "size": 0.1, "x": 50, "y": 50,
            "start_angle": 180, "sweep_angle": 180,
            "needle_length": 1.1, "needle_width": 4,
            "needle_color": "#DC3232", "show_value": show_value,
            "text_color": "#00FF00", "min_val": 0, "max_val": 180,
            "ticks": 10, "thickness": 1,
        }
        img, _, _, _ = _render_gauge_indicator(
            1920, 1080, {"indicators": {"speed_visual": cfg}}, "",
            "speed_visual", 45.0, "km/h", "Speed",  # label must NOT override value
            cfg, 1080, 3, 16, None, 0, 180, 10, 20, 100, 1,
            formatted_val=formatted_val,
        )
        return img

    def count_value_text(img):
        px = img.load()
        n = 0
        for y in range(120, 150):   # centre-text row band
            for x in range(img.size[0]):
                r, g, b, a = px[x, y]
                if g > 200 and r < 100 and b < 100 and a > 200:
                    n += 1
        return n

    img_on = render_centre(True, "45.0 km/h")
    img_off = render_centre(False, "")
    assert count_value_text(img_on) > 0    # value drawn (not the label)
    assert count_value_text(img_off) == 0  # show_value off -> hidden


# ── Units (Właściwości) ────────────────────────────────────────────────────

def test_gauge_schema_has_unit_field():
    """Właściwości for a gauge must expose a configurable 'Jednostka' field."""
    from src.gui.qt.models import gauge_indicator_fields
    names = {f.name for f in gauge_indicator_fields()}
    assert "unit" in names
    assert "show_units" in names


def test_gauge_units_show_with_empty_config_unit():
    """An empty 'unit' in the layout must fall back to the default unit."""
    from src.indicators.compositor import compose_overlay

    def value_text_width(show_units):
        cfg = {
            "enabled": True, "label": "", "x": 50.0, "y": 78.0, "rotation": 0,
            "form": "gauge", "font_size": 1.25, "size": 10.8, "thickness": 0.7,
            "min_val": 0, "max_val": 60, "ticks": 6, "source": "gpmf",
            "unit": "", "show_value": True, "show_units": show_units,
            "text_color": "#00FF00",
        }
        layout = {"global": {"text_outline": 3}, "indicators": {"speed_visual": cfg}}
        img = compose_overlay(
            1920, 1080, layout, "", "", "", 45.0, 0.0, 0.0, 0.0,
            0, 0, 0, 0, 0.0, indicator_values={}, max_speed_kmh=60.0,
        )
        px = img.load()
        xs = [x for y in range(700, 1000) for x in range(600, 1300)
              if px[x, y][1] > 200 and px[x, y][0] < 100 and px[x, y][3] > 200]
        return (max(xs) - min(xs)) if xs else 0

    on_w = value_text_width(True)   # "45.0 km/h" (default unit)
    off_w = value_text_width(False)  # "45.0"
    assert on_w > off_w + 10  # the unit text is present when Units is ON


def test_frame_data_fit_unit_hint():
    """FIT fields get a sensible unit even when the layout unit is empty."""
    from datetime import datetime, timezone
    from src.indicators.frame_data import prepare_overlay_frame_data

    dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    layout = {"indicators": {"fit_enhanced_speed_text": {
        "form": "gauge", "unit": "", "label": "Enhanced Speed"}}}
    data = prepare_overlay_frame_data(
        layout=layout, target_dt=dt, tz_offset_hours=0, start_dt_utc=dt,
        speed_samples=[], track_samples=[], alt_samples=[],
        extra_field_keys=["enhanced_speed"],
    )
    _, unit, _ = data["extra_indicators"]["fit_enhanced_speed_text"]
    assert unit == "km/h"
