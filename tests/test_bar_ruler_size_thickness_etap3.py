"""ETAP 3: vertical Ruler size scaling and fractional tick thickness."""

from __future__ import annotations

import json

import numpy as np

from src.gui.qt.models import bar_indicator_fields
from src.indicators.compositor import normalize_layout_for_save
from src.indicators.dispatcher import render_value_indicator


W, H = 1280, 720


def _cfg(**over):
    cfg = {
        "enabled": True, "form": "bar", "bar_style": "ruler",
        "orientation": "vertical", "label": "ALT", "unit": "m",
        "x": 50.0, "y": 50.0,
        "size": 1.0, "font_size": 1.2, "thickness": 1.0,
        "min_val": 0.0, "max_val": 100.0, "major_ticks": 5,
        "minor_ticks": 2, "show_value": True, "show_label": True,
        "show_range_labels": True, "range_units": True,
        "marker_size": 6.0,
    }
    cfg.update(over)
    return cfg


def _render(cfg):
    layout = {"global": {}, "indicators": {"r": cfg}}
    return render_value_indicator(
        W, H, layout, "", "r", 50.0, cfg["unit"], cfg["label"],
        formatted_val="50.0 m",
    )[0]


def test_vertical_size_scales_whole_widget_bbox():
    full = _render(_cfg(size=1.0))
    three_quarters = _render(_cfg(size=0.75))
    half = _render(_cfg(size=0.5))

    assert full.width > three_quarters.width > half.width
    assert full.height > three_quarters.height > half.height


def test_fractional_thickness_changes_vertical_raster():
    thin = _render(_cfg(thickness=0.5))
    normal = _render(_cfg(thickness=1.0))
    assert not np.array_equal(np.asarray(thin), np.asarray(normal))
    assert np.count_nonzero(np.asarray(thin)[:, :, 3]) != np.count_nonzero(
        np.asarray(normal)[:, :, 3]
    )


def test_horizontal_ruler_remains_horizontal():
    image = _render(_cfg(orientation="horizontal", size=20.0, thickness=1.0))
    assert image.width > image.height


def test_gui_schema_accepts_quarter_step_fractional_values():
    fields = {field.name: field for field in bar_indicator_fields("ruler")}
    size = fields["size"]
    thickness = fields["thickness"]
    assert size.min_val == 0.5
    assert thickness.field_type == "float"
    assert thickness.min_val == 0.25
    assert thickness.step == 0.25


def test_fractional_values_survive_layout_save_and_json_load():
    layout = {"indicators": {"r": _cfg(size=0.75, thickness=0.5)}}
    saved = normalize_layout_for_save(layout)
    encoded = json.dumps(saved)
    loaded = json.loads(encoded)
    assert loaded["indicators"]["r"]["size"] == 0.75
    assert loaded["indicators"]["r"]["thickness"] == 0.5
