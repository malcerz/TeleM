"""Tests for size/font_size handling in the indicator property panel.

Regression: "Size" on the Text tab (font_size) must affect only the label font
for gauge/chart/bar — it must NOT resize the whole widget (which `size` does).
For the text form the two stay in sync (unchanged behaviour).

The logic lives in the dependency-free ``_sync_size_font_fields`` helper
(``src.gui.qt.models``), so these tests stay fast without importing the full
Qt/OpenCL GUI stack.
"""

from __future__ import annotations

from src.gui.qt.models import _sync_size_font_fields


def test_chart_font_size_does_not_change_chart_size():
    """Text-tab Size (font_size) must not resize the chart widget."""
    cfg = {"enabled": True, "form": "chart", "size": 30.0, "font_size": 2.5}
    cfg["font_size"] = 5.0
    _sync_size_font_fields(cfg, "font_size")
    assert cfg["font_size"] == 5.0
    assert cfg["size"] == 30.0  # unchanged — chart width stays


def test_gauge_font_size_does_not_change_gauge_size():
    """Text-tab Size (font_size) must not resize the gauge."""
    cfg = {"enabled": True, "form": "gauge", "size": 12.0, "font_size": 2.0}
    cfg["font_size"] = 4.0
    _sync_size_font_fields(cfg, "font_size")
    assert cfg["font_size"] == 4.0
    assert cfg["size"] == 12.0  # unchanged


def test_bar_font_size_does_not_change_bar_size():
    """Text-tab Size (font_size) must not resize the bar."""
    cfg = {"enabled": True, "form": "bar", "size": 20.0, "font_size": 2.0}
    cfg["font_size"] = 3.0
    _sync_size_font_fields(cfg, "font_size")
    assert cfg["font_size"] == 3.0
    assert cfg["size"] == 20.0  # unchanged


def test_text_font_size_still_syncs_size():
    """For the text form, Size and font_size stay in sync (unchanged)."""
    cfg = {"enabled": True, "form": "text", "size": 10.0, "font_size": 2.0}
    cfg["font_size"] = 3.0
    _sync_size_font_fields(cfg, "font_size")
    assert cfg["font_size"] == 3.0
    assert cfg["size"] == 3.0


def test_text_size_still_syncs_font_size():
    """Changing "Rozmiar" on a text indicator still updates font_size."""
    cfg = {"enabled": True, "form": "text", "size": 10.0, "font_size": 2.0}
    cfg["size"] = 7.0
    _sync_size_font_fields(cfg, "size")
    assert cfg["size"] == 7.0
    assert cfg["font_size"] == 7.0

