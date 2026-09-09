from PIL import ImageChops

from src.indicators.bar import clear_bar_cache
from src.indicators.dispatcher import render_value_indicator
from src.indicators.lean import lean_visual_angle
from src.gui.qt.models import bar_indicator_fields


def _bar_cfg(**extra):
    cfg = {
        "enabled": True, "form": "bar", "bar_style": "ruler",
        "orientation": "horizontal", "x": 50.0, "y": 50.0,
        "size": 100.0, "font_size": 2.0, "show_label": True,
        "show_value": True, "show_range_labels": True,
        "min_val": 0.0, "max_val": 100.0,
    }
    cfg.update(extra)
    return cfg


def _render(cfg):
    return render_value_indicator(
        640, 360, {"global": {}, "indicators": {}}, "",
        "dist_visual", 50.0, "km", "DISTANCE", cfg_override=cfg,
        formatted_val="50 km",
    )[0]


def test_bar_auto_label_is_pixel_compatible_with_missing_property():
    clear_bar_cache()
    old = _render(_bar_cfg())
    clear_bar_cache()
    auto = _render(_bar_cfg(label_position="auto", label_offset_x=0, label_offset_y=0))
    assert ImageChops.difference(old, auto).getbbox() is None


def test_bar_label_positions_and_offsets_change_geometry_without_clipping():
    clear_bar_cache()
    images = {p: _render(_bar_cfg(label_position=p)) for p in ("top", "bottom", "left", "right", "inside")}
    assert images["left"].width > images["inside"].width
    assert images["right"].width > images["inside"].width
    assert images["top"].height > images["inside"].height
    assert images["bottom"].height > images["inside"].height
    for image in images.values():
        assert image.getchannel("A").getbbox() is not None


def test_bar_vertical_and_rotated_label_controls_are_renderable():
    for rotation in (0, 90, 180, 270):
        cfg = _bar_cfg(orientation="vertical", rotation=rotation, label_position="right",
                       label_offset_x=20, label_offset_y=-20)
        image = _render(cfg)
        assert image.getchannel("A").getbbox() is not None


def test_lean_calibration_contract_remains_unchanged():
    assert lean_visual_angle(0.0, {"calibration": 6.0}) == 6.0
    assert lean_visual_angle(-6.0, {"calibration": 6.0}) == 0.0


def test_bar_label_controls_are_exposed_in_polish_gui_schema():
    fields = {field.name: field for field in bar_indicator_fields()}
    assert fields["label_position"].label == "Pozycja etykiety"
    assert [choice[0] for choice in fields["label_position"].choices] == [
        "auto", "top", "bottom", "left", "right", "inside",
    ]
    assert fields["label_offset_x"].label == "Przesunięcie etykiety X"
    assert fields["label_offset_y"].label == "Przesunięcie etykiety Y"
    assert fields["label_offset_x"].min_val == -500.0
    assert fields["label_offset_x"].max_val == 500.0
