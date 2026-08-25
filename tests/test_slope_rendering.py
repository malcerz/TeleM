"""CPU_REFERENCE rendering and binding tests for ETAP 8E Slope."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import src.indicators.compositor as compositor_module
from src.gui.qt.models import get_schema_for_form
from src.indicators.bar import _format_slope_number, _render_bar_indicator
from src.indicators.compositor import compose_overlay
from src.indicators.registry import get_form_for_key
from src.indicators.frame_data import build_active_fit_field_plan, prepare_overlay_frame_data


def _cfg(**overrides):
    cfg = {
        "enabled": True,
        "label": "SLOPE",
        "field": "slope",
        "source": "gpmf",
        "x": 68.0,
        "y": 53.0,
        "rotation": 0,
        "form": "bar",
        "bar_style": "slope",
        "size": 20.0,
        "font_size": 1.35,
        "thickness": 2,
        "min_val": -20.0,
        "max_val": 20.0,
        "major_tick": 5.0,
        "minor_tick": 1.0,
        "show_value": True,
        "show_label": True,
        "show_range_labels": True,
        "show_units": True,
        "decimals": 1,
        "unit": "%",
        "track_color": "#8D9AA7",
        "tick_color": "#DDE7F2",
        "zero_tick_color": "#FFFFFF",
        "marker_color": "#FFD42A",
        "marker_border_color": "#FFFFFF",
        "marker_size": 6.0,
    }
    cfg.update(overrides)
    return cfg


def _render(value: float, *, missing: bool = False, rotation: int = 0):
    cfg = _cfg(_slope_missing=missing, rotation=rotation)
    value_text = "--%" if missing else f"{value:+.1f}%"
    return _render_bar_indicator(
        3840, 2160, {"indicators": {"slope_text": cfg}}, "",
        "slope_text", 0.0 if missing else value, "%", "SLOPE", cfg,
        2160, 2, 29, None, -20.0, 20.0, 0, 3, 768, 1,
        formatted_val=value_text,
    )[0]


def _yellow_points(image):
    arr = np.asarray(image)
    mask = (
        (arr[:, :, 0] > 200) & (arr[:, :, 1] > 150) &
        (arr[:, :, 2] < 100) & (arr[:, :, 3] > 150)
    )
    return np.argwhere(mask)


@pytest.mark.parametrize("value", [20.0, 10.0, 5.0, 0.0, -5.0, -10.0, -20.0])
def test_slope_renders_positive_negative_and_zero_marker(value):
    image = _render(value)
    assert image.getbbox() is not None
    assert len(_yellow_points(image)) > 0


def test_slope_none_keeps_scale_without_false_zero_marker():
    image = _render(0.0, missing=True)
    assert image.getbbox() is not None
    assert len(_yellow_points(image)) == 0


def test_slope_overflow_clamps_marker_but_not_value_format():
    high = _render(30.0)
    low = _render(-30.0)
    assert _yellow_points(high).mean(axis=0)[0] < _yellow_points(low).mean(axis=0)[0]
    assert _format_slope_number(26.0, 1) == "+26.0"
    assert _format_slope_number(-3.1, 1) == "-3.1"


def test_slope_geometry_fits_4k_1080p_and_720p():
    for canvas_w, canvas_h in ((3840, 2160), (1920, 1080), (1280, 720)):
        cfg = _cfg()
        size_px = round(cfg["size"] / 100.0 * canvas_w)
        image, *_ = _render_bar_indicator(
            canvas_w, canvas_h, {"indicators": {"slope_text": cfg}}, "",
            "slope_text", 6.4, "%", "SLOPE", cfg, canvas_h, 2,
            max(8, round(cfg["font_size"] / 100.0 * canvas_h)), None,
            -20.0, 20.0, 0, 3, size_px, 1, formatted_val="+6.4%",
        )
        assert image.getbbox() is not None
        assert 500 <= image.height <= 950 if canvas_w == 3840 else image.height > 200
        alpha = np.asarray(image)[:, :, 3]
        ys, xs = np.where(alpha > 0)
        assert xs.min() >= 0 and ys.min() >= 0
        assert xs.max() < image.width and ys.max() < image.height


def test_slope_rotation_is_supported_by_compositor_bbox():
    layout = {"global": {}, "indicators": {"slope_text": _cfg(rotation=0)}}
    normal_bboxes = {}
    normal = compose_overlay(
        1920, 1080, layout, "", "", "", 0.0, 0.0,
        indicator_values={"slope_text": 6.4}, _bboxes=normal_bboxes,
        reuse_canvas=False,
    )
    layout["indicators"]["slope_text"]["rotation"] = 90
    rotated_bboxes = {}
    rotated = compose_overlay(
        1920, 1080, layout, "", "", "", 0.0, 0.0,
        indicator_values={"slope_text": 6.4}, _bboxes=rotated_bboxes,
        reuse_canvas=False,
    )
    assert normal.getbbox() is not None and rotated.getbbox() is not None
    assert normal_bboxes["slope_text"][2] != rotated_bboxes["slope_text"][2]
    assert normal_bboxes["slope_text"][3] != rotated_bboxes["slope_text"][3]


@pytest.mark.parametrize("source", ["fit", "gpmf"])
def test_slope_source_binding_uses_requested_source_only(source):
    layout = {"indicators": {"slope_text": {
        **_cfg(source=source), "enabled": True,
    }}}
    plan = build_active_fit_field_plan(layout, [])
    calls = []

    def resolve(field, source, target_dt, *args):
        calls.append((field, source))
        return 4.5

    data = prepare_overlay_frame_data(
        layout=layout, target_dt=None, tz_offset_hours=0.0, start_dt_utc=None,
        speed_samples=[], track_samples=[], alt_samples=[],
        fit_field_plan=plan, resolve_cache_value=resolve,
    )
    assert data["extra_indicators"]["slope_text"] == (4.5, "%", "SLOPE")
    assert calls == [("slope", source)]


def test_slope_schema_registry_and_preset_are_configurable():
    fields = {field.name for field in get_schema_for_form("bar", bar_style="slope")}
    for name in ("source", "field", "x", "y", "size", "rotation", "opacity",
                 "min_val", "max_val", "major_tick", "minor_tick",
                 "show_value", "show_label", "show_range_labels"):
        assert name in fields
    assert get_form_for_key("slope_text") == ("bar", {"form": "bar", "size": 20.0, "bar_style": "slope"})

    v4 = json.loads(Path("presets/cycling_dashboard_v4.json").read_text(encoding="utf-8"))
    v5 = json.loads(Path("presets/cycling_dashboard_v5.json").read_text(encoding="utf-8"))
    assert v5["preset_name"] == "cycling_dashboard_v5"
    for key, cfg in v4["indicators"].items():
        assert v5["indicators"][key] == cfg
    slope = v5["indicators"]["slope_text"]
    assert slope["field"] == "slope"
    assert slope["bar_style"] == "slope"
    assert slope["min_val"] == -20.0 and slope["max_val"] == 20.0
    assert slope["major_tick"] == 5.0 and slope["minor_tick"] == 1.0


def test_slope_preset_json_roundtrip_preserves_editable_properties(tmp_path):
    preset = json.loads(Path("presets/cycling_dashboard_v5.json").read_text(encoding="utf-8"))
    slope = preset["indicators"]["slope_text"]
    slope.update({"source": "fit", "min_val": -15.0, "max_val": 18.0,
                  "major_tick": 3.0, "show_value": False})
    path = tmp_path / "cycling_dashboard_v5_custom.json"
    path.write_text(json.dumps(preset, indent=2), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["indicators"]["slope_text"] == slope


def test_slope_compositor_formats_overflow_and_missing_value(monkeypatch):
    captured = []

    def fake_render(*args, **kwargs):
        cfg = kwargs["cfg_override"]
        captured.append((args[4], kwargs.get("formatted_val"), cfg.get("_slope_missing", False)))
        return Image.new("RGBA", (4, 4), (255, 255, 255, 255)), 100, 100, None

    monkeypatch.setattr(compositor_module, "render_value_indicator", fake_render)
    layout = {"global": {}, "indicators": {"slope_text": _cfg()}}
    compose_overlay(
        1920, 1080, layout, "", "", "", 0.0, 0.0,
        indicator_values={"slope_text": 26.0}, reuse_canvas=False,
    )
    compose_overlay(
        1920, 1080, layout, "", "", "", 0.0, 0.0,
        indicator_values={"slope_text": None}, reuse_canvas=False,
    )
    assert captured[0] == ("slope_text", "+26.0%", False)
    assert captured[1] == ("slope_text", "--%", True)
