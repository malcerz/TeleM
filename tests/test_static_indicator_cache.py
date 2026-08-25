from __future__ import annotations

from copy import deepcopy

from PIL import ImageChops

from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import _STATIC_CACHE, get_static_cache_stats


def _layout(form: str, **cfg):
    base = {
        "global": {"text_outline": 1},
        "indicators": {
            "probe": {
                "enabled": True, "x": 50.0, "y": 50.0,
                "form": form, "size": 18.5, "font_size": 1.2,
                "min_val": 0.0, "max_val": 100.0, "ticks": 6,
                "show_value": True, "unit": "", "label": "PROBE",
                **cfg,
            }
        },
    }
    return base


def _render(layout, value, *, history=None, font="arial.ttf", formatted="10"):
    return render_value_indicator(
        canvas_w=1280, canvas_h=720, layout=layout, font_path=font,
        key="probe", value=value, unit=layout["indicators"]["probe"].get("unit", ""),
        label="PROBE", cfg_override=layout["indicators"]["probe"],
        formatted_val=formatted, history_data=history, current_position=0.5,
    )[0]


def test_compass_cache_miss_hit_is_byte_identical_and_heading_is_dynamic():
    _STATIC_CACHE.clear()
    layout = _layout(
        "gauge", gauge_style="compass", tick_profile="pixel",
        compass_show_heading=True,
    )
    first = _render(layout, 0.0, formatted="000°")
    second = _render(layout, 0.0, formatted="000°")
    rotated = _render(layout, 90.0, formatted="090°")
    assert ImageChops.difference(first, second).getbbox() is None
    assert ImageChops.difference(first, rotated).getbbox() is not None
    assert get_static_cache_stats()["hits"] >= 1


def test_gauge_cache_hit_parity_and_dynamic_value():
    _STATIC_CACHE.clear()
    layout = _layout("gauge", tick_profile="pixel", unit="km/h")
    first = _render(layout, 10.0, formatted="10.0 km/h")
    second = _render(layout, 10.0, formatted="10.0 km/h")
    faster = _render(layout, 30.0, formatted="30.0 km/h")
    assert ImageChops.difference(first, second).getbbox() is None
    assert ImageChops.difference(first, faster).getbbox() is not None


def test_chart_static_cache_hit_and_history_change():
    _STATIC_CACHE.clear()
    layout = _layout(
        "chart", size=27.0, chart_window_s=60.0, chart_color="#FFD42A",
        fill_color="#FFD42A", show_grid=True, label_count=2,
    )
    history_a = {"values": [10.0, 20.0, 30.0]}
    history_b = {"values": [30.0, 20.0, 10.0]}
    first = _render(layout, 20.0, history=history_a, formatted="20")
    second = _render(layout, 20.0, history=history_a, formatted="20")
    changed = _render(layout, 20.0, history=history_b, formatted="20")
    assert ImageChops.difference(first, second).getbbox() is None
    assert ImageChops.difference(first, changed).getbbox() is not None


def test_slope_dynamic_marker_and_static_style_miss():
    _STATIC_CACHE.clear()
    layout = _layout(
        "bar", bar_style="slope", size=15.0, min_val=-20.0, max_val=20.0,
        major_tick=5.0, minor_tick=1.0, tick_profile="pixel", unit="%",
    )
    negative = _render(layout, -5.0, formatted="-5%")
    same = _render(layout, -5.0, formatted="-5%")
    positive = _render(layout, 5.0, formatted="+5%")
    assert ImageChops.difference(negative, same).getbbox() is None
    assert ImageChops.difference(negative, positive).getbbox() is not None

    styled = deepcopy(layout)
    styled["indicators"]["probe"]["tick_color"] = "#FF00FF"
    _render(styled, -5.0, formatted="-5%")
    assert get_static_cache_stats()["misses"] >= 2


def test_compass_none_does_not_reuse_previous_needle():
    _STATIC_CACHE.clear()
    layout = _layout("gauge", gauge_style="compass", compass_show_heading=True)
    present = _render(layout, 45.0, formatted="045°")
    missing = _render(layout, None, formatted="--°")
    assert ImageChops.difference(present, missing).getbbox() is not None


def test_static_cache_is_bounded():
    _STATIC_CACHE.clear()
    for index in range(200):
        _STATIC_CACHE[("test", index)] = index
    stats = get_static_cache_stats()
    assert stats["entries"] <= stats["max_entries"]
    assert stats["max_entries"] == 128
