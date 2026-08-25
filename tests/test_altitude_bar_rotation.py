"""Focused regression tests for legacy altitude-bar orientation."""

from src.indicators.compositor import (
    _effective_indicator_cfg,
    compose_overlay,
    normalize_layout_for_save,
)


def _legacy_altitude_cfg():
    return {
        "enabled": True,
        "form": "bar",
        "bar_style": "ruler",
        "x": 5.5,
        "y": 52.0,
        "rotation": 90,
        "font_size": 1.38,
        "size": 16.0,
        "thickness": 1,
        "min_val": 0.0,
        "max_val": 1000.0,
        "ticks": 5,
        "show_value": True,
        "show_label": False,
        "show_range_labels": True,
        "range_units": True,
        "unit": "m",
        "decimals": 0,
    }


def test_legacy_altitude_rotation_migrates_to_vertical_ruler_text_contract():
    effective = _effective_indicator_cfg("alt_visual", _legacy_altitude_cfg())
    assert effective["orientation"] == "vertical"
    assert effective["rotation"] == 0


def test_legacy_alt_text_ruler_migrates_by_semantics_not_indicator_id():
    effective = _effective_indicator_cfg("alt_text", _legacy_altitude_cfg())
    assert effective["orientation"] == "vertical"
    assert effective["rotation"] == 0


def test_explicit_vertical_bar_rotation_is_not_overwritten():
    cfg = _legacy_altitude_cfg()
    cfg["orientation"] = "vertical"
    effective = _effective_indicator_cfg("alt_visual", cfg)
    assert effective["orientation"] == "vertical"
    assert effective["rotation"] == 90


def test_save_migrates_legacy_ruler_without_mutating_runtime_layout():
    layout = {"indicators": {"alt_text": _legacy_altitude_cfg()}}
    saved = normalize_layout_for_save(layout)
    assert saved["indicators"]["alt_text"]["orientation"] == "vertical"
    assert saved["indicators"]["alt_text"]["rotation"] == 0
    assert "orientation" not in layout["indicators"]["alt_text"]
    assert layout["indicators"]["alt_text"]["rotation"] == 90


def test_legacy_altitude_compositor_bbox_is_vertical():
    layout = {"indicators": {"alt_visual": _legacy_altitude_cfg()}, "custom_texts": [], "global": {}}
    bboxes = {}
    compose_overlay(
        1280, 720, layout, "", "01", "02", 1.0, 2.0, 3.0,
        345.0, 0.0, 1000.0, _bboxes=bboxes,
    )
    x, y, width, height = bboxes["alt_visual"]
    assert width > 0 and height > 0
    assert height > width


def test_explicit_horizontal_and_vertical_rulers_keep_geometry_contract():
    for orientation, vertical in (("horizontal", False), ("vertical", True)):
        cfg = _legacy_altitude_cfg()
        cfg["orientation"] = orientation
        cfg["rotation"] = 0
        layout = {"indicators": {"alt_text": cfg}, "custom_texts": [], "global": {}}
        bboxes = {}
        compose_overlay(
            1280, 720, layout, "", "01", "02", 1.0, 2.0, 3.0,
            345.0, 0.0, 1000.0, _bboxes=bboxes,
        )
        _, _, width, height = bboxes["alt_text"]
        assert (height > width) is vertical
