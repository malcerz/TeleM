from __future__ import annotations

from unittest import mock

from PIL import Image

from src.indicators.chart_utils import generate_nice_value_ticks
from src.indicators.compositor import render_preview
from src.indicators.helpers import (
    PREVIEW_VIDEO_BRIGHTNESS,
    dim_preview_video,
    resolve_decimal_places,
)
from src.gui.qt.models import chart_indicator_fields


def test_chart_decimal_places_formats_all_requested_precisions():
    value = 146.0
    assert [f"{value:.{places}f}" for places in range(4)] == [
        "146", "146.0", "146.00", "146.000",
    ]
    assert f"{123.456:.2f}" == "123.46"


def test_decimal_places_keeps_explicit_zero_and_legacy_alias():
    assert resolve_decimal_places({"decimal_places": 0}, default=1) == 0
    assert resolve_decimal_places({"decimals": 2}, default=1) == 2
    assert resolve_decimal_places({}, default=1) == 1


def test_chart_editor_exposes_global_decimal_places_control():
    field = next(field for field in chart_indicator_fields() if field.name == "decimal_places")
    assert field.label == "Miejsca po przecinku"
    assert (field.min_val, field.max_val, field.default) == (0, 2, 1)


def test_chart_axis_ticks_use_requested_decimal_places():
    _, _, labels = generate_nice_value_ticks(123.456, 123.456, 2, decimal_places=2)
    assert labels
    assert all("." in label and len(label.rsplit(".", 1)[1]) == 2 for label in labels)


def test_chart_autoscale_receives_raw_values(monkeypatch):
    from src.indicators import chart_utils

    captured = {}

    def fake_ticks(data_min, data_max, target_count=5, decimal_places=0):
        captured["range"] = (data_min, data_max)
        captured["decimal_places"] = decimal_places
        return data_min, data_max + 1.0, ["123"]

    monkeypatch.setattr(chart_utils, "generate_nice_value_ticks", fake_ticks)
    chart_utils._build_chart_bg(
        [123.456, 234.567], 120, 60,
        (255, 255, 255), 2, 40, None, True, None, None, None, 1,
        None, None, 2, False, "", False, None, None,
        decimal_places=0,
    )
    assert captured == {
        "range": (123.456, 234.567),
        "decimal_places": 0,
    }


def test_dynamic_fit_chart_uses_same_decimal_control(monkeypatch):
    from src.indicators import compositor

    captured = {}

    def fake_render(*args, **kwargs):
        captured["formatted_val"] = kwargs["formatted_val"]
        return Image.new("RGBA", (1, 1), (255, 255, 255, 255)), 0, 0, None

    monkeypatch.setattr(compositor, "render_value_indicator", fake_render)
    compositor.compose_overlay(
        320, 180,
        {"indicators": {"fit_custom_text": {
            "enabled": True, "form": "chart", "decimal_places": 2,
            "x": 50, "y": 50, "size": 0.2,
        }}},
        None, "", "", 0.0, 0.0,
        extra_indicators={"fit_custom_text": (123.456, "u", "Custom")},
        chart_data={"fit_custom_text": [100.0, 123.456]},
        reuse_canvas=False,
    )
    assert captured["formatted_val"] == "123.46 u"


def test_preview_dim_changes_video_rgb_and_preserves_alpha():
    source = Image.new("RGBA", (2, 1), (100, 80, 60, 123))
    dimmed = dim_preview_video(source)
    assert dimmed.getpixel((0, 0))[:3] == (55, 44, 33)
    assert dimmed.getpixel((0, 0))[3] == 123


def test_edit_preview_composes_hud_without_dimming_video():
    source = Image.new("RGBA", (2, 1), (100, 80, 60, 255))
    overlay = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    overlay.putpixel((1, 0), (240, 230, 220, 255))

    with mock.patch("src.indicators.compositor.compose_overlay", return_value=overlay):
        result = render_preview(
            source, {}, None, "", "", 0.0, 0.0,
        )

    assert result.getpixel((0, 0)) == (100, 80, 60, 255)
    assert result.getpixel((1, 0)) == (240, 230, 220, 255)


def test_final_overlay_compositor_has_no_preview_dim_side_effect():
    from src.indicators.compositor import compose_overlay

    source = Image.new("RGBA", (2, 1), (100, 80, 60, 255))
    overlay = compose_overlay(
        2, 1, {"indicators": {}}, None, "", "", 0.0, 0.0,
        reuse_canvas=False,
    )
    expected = source.copy()
    expected.alpha_composite(overlay)
    result = render_preview(
        source, {"indicators": {}}, None, "", "", 0.0, 0.0,
    )
    assert result.tobytes() == expected.tobytes()
