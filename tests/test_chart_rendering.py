"""Tests for src/indicators/chart_utils.py + chart.py — chart scale behaviour.

Covers:
- the line must align exactly with the Y-axis labels/gridlines (no v_margin
  inset) so a value at max_val plots on the top label row,
- small charts must keep a usable plot area (fixed 50/22px margins used to
  collapse them to ~1px and push labels off-screen),
- newly-added chart indicators get a sensible default size (registry).
"""

from __future__ import annotations

import pytest

from src.indicators.chart_utils import generate_history_chart


def _blue_rows(img):
    """Return the min/max y of blue (chart line) pixels."""
    px = img.load()
    ys = [y for x in range(img.size[0]) for y in range(img.size[1])
          if px[x, y][0] < 120 and px[x, y][2] > 180 and px[x, y][3] > 200]
    return (min(ys), max(ys)) if ys else (None, None)


def test_chart_line_aligns_with_axis_labels():
    """A data point at max_val must sit on the top label row, min on the bottom."""
    from src.indicators.chart_utils import get_history_chart_background
    _, _, plot_y1, plot_y2, _, _ = get_history_chart_background(
        [0, 100], 400, 200, line_color=(0, 170, 255),
        line_thickness=2, fill_alpha=40, fill_color=(0, 170, 255),
        show_axes=True, grid_color=(68, 68, 68, 60), supersample=1,
        custom_min_val=0.0, custom_max_val=100.0, label_count=2,
    )
    img = generate_history_chart(
        [0, 100], 400, 200, line_color=(0, 170, 255),
        line_thickness=2, fill_alpha=40, fill_color=(0, 170, 255),
        show_axes=True, grid_color=(68, 68, 68, 60), supersample=1,
        custom_min_val=0.0, custom_max_val=100.0, label_count=2,
    )
    top, bot = _blue_rows(img)
    assert top is not None and bot is not None
    assert abs(top - plot_y1) <= 1   # max value -> top label/gridline
    assert abs(bot - plot_y2) <= 1   # min value -> bottom axis


def test_chart_small_size_keeps_usable_plot():
    """A 31px-wide chart (def_layout size=1.6) must not collapse to a 1px plot."""
    img = generate_history_chart(
        [0, 50, 100], 31, 40, line_color=(0, 170, 255),
        line_thickness=1, fill_alpha=40, fill_color=(0, 170, 255),
        show_axes=True, grid_color=(68, 68, 68, 60), supersample=1,
        custom_min_val=0.0, custom_max_val=100.0, label_count=2,
    )
    px = img.load()
    xs = [x for y in range(img.size[1]) for x in range(img.size[0])
          if px[x, y][3] > 0]
    assert xs
    # before the fix the plot area collapsed to ~1px; now content spans the width
    assert max(xs) - min(xs) > img.size[0] * 0.5
    # the data line itself must be visible
    top, bot = _blue_rows(img)
    assert top is not None


def test_chart_accepts_font_scale_params():
    """generate_history_chart must accept the new label sizing parameters."""
    img = generate_history_chart(
        [0, 50, 100], 300, 150, line_color=(0, 170, 255),
        line_thickness=2, show_axes=True, grid_color=(68, 68, 68, 60),
        supersample=1, custom_min_val=0.0, custom_max_val=100.0,
        label_count=3, label_font_size=14, font_path="",
    )
    assert img.size == (300, 150)


def test_registry_chart_default_size_is_reasonable():
    """Newly-added chart indicators must not be ~6px wide (was 0.3 → 0.3%)."""
    from src.indicators.registry import get_form_for_key
    form, overrides = get_form_for_key("heart_rate")
    assert form == "chart"
    assert overrides["size"] >= 20


# ── Schema: no dead fields, negative min ───────────────────────────────────

def test_chart_schema_has_no_dead_fields():
    """Chart Właściwości must not expose controls the renderer ignores."""
    from src.gui.qt.models import chart_indicator_fields
    names = {f.name for f in chart_indicator_fields()}
    for dead in ("ticks", "window_s"):
        assert dead not in names
    for used in ("label_count", "label_font_size", "label_units", "show_average",
                 "thickness", "min_val", "max_val", "line_width", "fill_alpha",
                 "show_grid", "chart_color", "fill_color", "grid_color",
                 "show_value", "show_units", "text_color"):
        assert used in names


def test_chart_schema_min_val_allows_negative():
    """Ticks-tab Minimum/Maksimum must support negative ranges (e.g. °C/alt)."""
    from src.gui.qt.models import chart_indicator_fields
    fields = {f.name: f for f in chart_indicator_fields()}
    assert fields["min_val"].min_val < 0
    assert fields["max_val"].min_val < 0


# ── Axis labels must never clip (margin sized to the widest label) ─────────

def _grey_label_extent(img):
    """Return (min_x, max_x) of grey axis-label pixels, or None."""
    px = img.load()
    xs = [x for y in range(img.size[1]) for x in range(img.size[0])
          if 185 <= px[x, y][0] <= 215 and 185 <= px[x, y][1] <= 215
          and 185 <= px[x, y][2] <= 215 and px[x, y][3] > 200]
    return (min(xs), max(xs)) if xs else None


def test_chart_axis_labels_not_clipped_with_units():
    """Long Y labels with units must stay fully on-image on a small chart."""
    img = generate_history_chart(
        [60, 120, 180], 80, 60, line_color=(0, 170, 255),
        line_thickness=2, fill_alpha=40, fill_color=(0, 170, 255),
        show_axes=True, grid_color=(68, 68, 68, 60), supersample=1,
        custom_min_val=60.0, custom_max_val=180.0,
        label_count=2, label_units=True, unit="km/h",
    )
    extent = _grey_label_extent(img)
    assert extent is not None          # labels are drawn
    assert extent[0] > 0               # and not cut off at the left edge
