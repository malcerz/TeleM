from __future__ import annotations

import json
from pathlib import Path

from PIL import ImageChops

from src.indicators.compositor import compose_overlay


FONT = r"C:\Windows\Fonts\arial.ttf"


def _render(cfg: dict, *, key: str, value: float = 25.0):
    layout = {"global": {"text_outline": 1}, "indicators": {key: cfg}}
    return compose_overlay(
        1280, 720, layout, FONT, "2026-08-14", "11:23:03", 25.0, 1000.0,
        indicator_values={key: value}, render_keys={key}, reuse_canvas=False,
    )


def _gauge(profile: str | None = None) -> dict:
    cfg = {
        "enabled": True, "form": "gauge", "x": 50.0, "y": 50.0,
        "size": 18.5, "font_size": 2.2, "min_val": 0.0, "max_val": 60.0,
        "ticks": 6, "start_angle": 0, "sweep_angle": 360,
        "show_value": True, "show_marker": True, "marker_size": 5,
    }
    if profile is not None:
        cfg["tick_profile"] = profile
    return cfg


def _ruler(profile: str | None = None) -> dict:
    cfg = {
        "enabled": True, "form": "bar", "bar_style": "ruler",
        "x": 50.0, "y": 50.0, "size": 28.0, "font_size": 1.2,
        "min_val": 0.0, "max_val": 10.0, "ticks": 5,
        "major_ticks": 5, "minor_ticks": 1, "show_value": True,
        "show_range_labels": True,
    }
    if profile is not None:
        cfg["tick_profile"] = profile
    return cfg


def test_default_gauge_and_bar_are_unchanged_without_profile() -> None:
    assert _render(_gauge(), key="speed_visual").tobytes() == _render(
        _gauge("default"), key="speed_visual"
    ).tobytes()
    assert _render(_ruler(), key="dist_visual").tobytes() == _render(
        _ruler("default"), key="dist_visual"
    ).tobytes()


def test_pixel_gauge_and_ruler_have_distinct_raster_profiles() -> None:
    assert ImageChops.difference(
        _render(_gauge(), key="speed_visual"),
        _render(_gauge("pixel"), key="speed_visual"),
    ).getbbox() is not None
    assert ImageChops.difference(
        _render(_ruler(), key="dist_visual"),
        _render(_ruler("pixel"), key="dist_visual"),
    ).getbbox() is not None


def test_pixel_compass_and_slope_profiles_render() -> None:
    compass = {
        "enabled": True, "form": "gauge", "gauge_style": "compass",
        "x": 50.0, "y": 50.0, "size": 12.0, "font_size": 1.2,
        "compass_tick_degrees": 5, "compass_major_tick_degrees": 45,
        "tick_profile": "pixel",
    }
    slope = {
        "enabled": True, "form": "bar", "bar_style": "slope",
        "x": 50.0, "y": 50.0, "size": 15.0, "font_size": 1.35,
        "min_val": -20.0, "max_val": 20.0, "major_tick": 5.0,
        "minor_tick": 1.0, "tick_profile": "pixel",
    }
    assert _render(compass, key="compass", value=123).getbbox() is not None
    assert _render(slope, key="slope_text", value=4).getbbox() is not None


def test_v8_load_and_only_pixel_profiles_are_opted_in() -> None:
    v7 = json.loads(Path("presets/cycling_dashboard_v7.json").read_text(encoding="utf-8"))
    v8 = json.loads(Path("presets/cycling_dashboard_v8.json").read_text(encoding="utf-8"))
    assert v7["preset_name"] == "cycling_dashboard_v7"
    assert v8["preset_name"] == "cycling_dashboard_v8"
    assert v8["indicators"]["fit_enhanced_speed_text"]["tick_profile"] == "pixel"
    assert "tick_profile" not in v7["indicators"]["fit_enhanced_speed_text"]
    assert "font" not in v8["indicators"]["fit_enhanced_speed_text"]
