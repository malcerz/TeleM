from __future__ import annotations

import copy

from PIL import Image

from src.ffmpeg.command_builder import (
    _precise_text_box,
    build_text_bbox_context,
    get_layout_hud_regions,
)
from src.indicators.compositor import compose_overlay


def _text_layout(rotation: int = 0) -> dict:
    return {
        "global": {"text_outline": 3},
        "indicators": {
            "value_text": {
                "enabled": True, "form": "text", "x": 25.0, "y": 30.0,
                "rotation": rotation, "font_size": 2.5, "label": "Temperature",
                "unit": "°C", "decimals": 1, "show_units": True,
            }
        },
        "custom_texts": [],
    }


def test_precise_text_box_covers_short_and_long_rendered_values() -> None:
    layout = _text_layout()
    context = {"text_candidates": {"value_text": {"formatted_values": ["0.0 °C", "-123.4 °C", "9999.9 °C"]}}}
    box = _precise_text_box(layout, "value_text", layout["indicators"]["value_text"], 1920, 1080, context["text_candidates"], "")
    assert box is not None

    for value in (0.0, -123.4, 9999.9):
        image = compose_overlay(
            1920, 1080, {**layout, "indicators": {"value_text": copy.deepcopy(layout["indicators"]["value_text"])}}, "",
            "2026-08-20", "12:34:56", 0.0, 0.0,
            indicator_values={}, extra_indicators={"value_text": (value, "°C", "Temperature")},
            reuse_canvas=False,
        )
        alpha = image.getchannel("A").getbbox()
        assert alpha is not None
        actual = (alpha[0], alpha[1], alpha[2] - alpha[0], alpha[3] - alpha[1])
        assert actual[0] >= box[0]
        assert actual[1] >= box[1]
        assert actual[0] + actual[2] <= box[0] + box[2]
        assert actual[1] + actual[3] <= box[1] + box[3]


def test_precise_text_box_covers_all_supported_rotations() -> None:
    for rotation in (0, 90, 180, 270):
        layout = _text_layout(rotation)
        context = {"text_candidates": {"value_text": {"formatted_values": ["-123.4 °C", "9999.9 °C"]}}}
        box = _precise_text_box(layout, "value_text", layout["indicators"]["value_text"], 1920, 1080, context["text_candidates"], "")
        assert box is not None
        image = compose_overlay(
            1920, 1080, layout, "", "2026-08-20", "12:34:56", 0.0, 0.0,
            extra_indicators={"value_text": (9999.9, "°C", "Temperature")}, reuse_canvas=False,
        )
        alpha = image.getchannel("A").getbbox()
        assert alpha is not None
        actual = (alpha[0], alpha[1], alpha[2] - alpha[0], alpha[3] - alpha[1])
        assert actual[0] >= box[0]
        assert actual[1] >= box[1]
        assert actual[0] + actual[2] <= box[0] + box[2]
        assert actual[1] + actual[3] <= box[1] + box[3]


def test_phantom_detection_respects_fit_source_and_zero_is_data() -> None:
    layout = {
        "indicators": {
            "fit_battery_text": {"enabled": True, "form": "text", "source": "fit", "x": 10, "y": 10, "label": "Battery"},
            "fit_cadence_text": {"enabled": True, "form": "text", "source": "fit", "x": 10, "y": 20, "label": "Cadence"},
        }
    }
    missing = build_text_bbox_context(layout, fit_data={})
    assert missing["phantom_keys"] == {"fit_battery_text", "fit_cadence_text"}

    gpmf_available = build_text_bbox_context(layout, fit_data={}, gpx_cad_samples=[(0.0, 88.0)])
    assert "fit_cadence_text" in gpmf_available["phantom_keys"]

    zero = build_text_bbox_context(layout, fit_data={"cadence": [(0.0, 0.0)]})
    assert "fit_cadence_text" not in zero["phantom_keys"]
    assert "fit_battery_text" in zero["phantom_keys"]


def test_phantom_is_excluded_from_transport_geometry_without_layout_mutation() -> None:
    layout = {
        "indicators": {
            "fit_battery_text": {"enabled": True, "form": "text", "source": "fit", "x": 90, "y": 10, "label": "Battery"},
            "fit_cadence_text": {"enabled": True, "form": "text", "source": "fit", "x": 10, "y": 80, "label": "Cadence"},
        }
    }
    original = copy.deepcopy(layout)
    context = build_text_bbox_context(layout, fit_data={"cadence": [(0.0, 0.0)]})
    _, _, regions = get_layout_hud_regions(
        layout, 1920, 1080, max_regions=3,
        text_candidates=context["text_candidates"], phantom_keys=context["phantom_keys"],
    )
    assert layout == original
    assert all(region[0] < 1000 for region in regions)
