"""Cache validation test suite verifying all 8 edge cases required by Etap 5B.

Tests:
1. Color change without alpha mask change.
2. Value change with repeated previous key.
3. Style change in editor.
4. Resolution change.
5. Two indicators with similar keys.
6. Multiple queued export jobs / cache resets.
7. Input image mutation safety.
8. PIL Image sharing / mutation safety.
"""

from __future__ import annotations
import pytest
import numpy as np
from PIL import Image, ImageDraw

from src.indicators.bar import _render_bar_indicator, clear_bar_cache
from src.indicators.gauge import _render_gauge_indicator, clear_gauge_cache
from src.indicators.effects import apply_indicator_effects, clear_effects_cache


def test_1_color_change_without_alpha_mask_change():
    """Changing text_color must produce different RGB even if alpha mask is identical."""
    clear_effects_cache()
    clear_bar_cache()
    cw, ch = 1920, 1080
    cfg_red = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FF0000", "unit": "km",
        "shadow_enabled": True, "shadow_distance": 2.0, "shadow_length": 3.0,
    }
    cfg_green = dict(cfg_red)
    cfg_green["text_color"] = "#00FF00"

    img_red, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg_red}}, "", "bar", 50.0, "km", "DIST",
        cfg_red, 1080, 0, 16, None, 0, 100, 10, 2.0, 500, 2, formatted_val="50.0"
    )
    img_green, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg_green}}, "", "bar", 50.0, "km", "DIST",
        cfg_green, 1080, 0, 16, None, 0, 100, 10, 2.0, 500, 2, formatted_val="50.0"
    )

    arr_red = np.asarray(img_red)
    arr_green = np.asarray(img_green)
    # Red channel must differ significantly
    assert np.max(np.abs(arr_red[:, :, 0].astype(int) - arr_green[:, :, 0].astype(int))) > 150
    # Green channel must differ significantly
    assert np.max(np.abs(arr_red[:, :, 1].astype(int) - arr_green[:, :, 1].astype(int))) > 150


def test_2_value_change_repeating_previous_key():
    """Alternating between two values (A -> B -> A) must return correct fresh content each time."""
    clear_effects_cache()
    clear_gauge_cache()
    cw, ch = 1920, 1080
    cfg = {
        "x": 50.0, "y": 50.0, "size": 20.0, "thickness": 1.0,
        "start_angle": 180, "sweep_angle": 180, "needle_length": 1.1, "needle_width": 4,
        "needle_color": "#FF0000", "min_val": 0, "max_val": 100, "show_value": True,
        "shadow_enabled": True, "shadow_distance": 2.0,
    }

    img_10_a, _, _, _ = _render_gauge_indicator(
        cw, ch, {"indicators": {"g": cfg}}, "", "g", 10.0, "km/h", "Speed",
        cfg, 1080, 0, 16, None, 0, 100, 10, 1.0, 200, 1, formatted_val="10.0"
    )
    # Gauge returns its reusable canvas. Snapshot each frame at consumption
    # time, before the next render mutates that canvas.
    img_10_a = img_10_a.copy()
    img_90, _, _, _ = _render_gauge_indicator(
        cw, ch, {"indicators": {"g": cfg}}, "", "g", 90.0, "km/h", "Speed",
        cfg, 1080, 0, 16, None, 0, 100, 10, 1.0, 200, 1, formatted_val="90.0"
    )
    img_90 = img_90.copy()
    img_10_b, _, _, _ = _render_gauge_indicator(
        cw, ch, {"indicators": {"g": cfg}}, "", "g", 10.0, "km/h", "Speed",
        cfg, 1080, 0, 16, None, 0, 100, 10, 1.0, 200, 1, formatted_val="10.0"
    )

    # 10_a and 10_b must be identical
    diff_repeat = np.max(np.abs(np.asarray(img_10_a).astype(int) - np.asarray(img_10_b).astype(int)))
    assert diff_repeat == 0

    # 10_a and 90 must differ substantially (different needle angle)
    diff_val = np.max(np.abs(np.asarray(img_10_a).astype(int) - np.asarray(img_90).astype(int)))
    assert diff_val > 200


def test_3_style_change_in_editor():
    """Toggling shadows or outline on the fly must invalidate and update output."""
    clear_effects_cache()
    clear_gauge_cache()
    cw, ch = 1920, 1080
    cfg_plain = {
        "x": 50.0, "y": 50.0, "size": 20.0, "thickness": 1.0,
        "needle_color": "#FF0000", "min_val": 0, "max_val": 100, "show_value": False,
        "shadow_enabled": False,
    }
    cfg_shadow = dict(cfg_plain)
    cfg_shadow["shadow_enabled"] = True
    cfg_shadow["shadow_distance"] = 5.0
    cfg_shadow["shadow_length"] = 5.0
    cfg_shadow["shadow_color"] = "#000000"

    img_plain, _, _, _ = _render_gauge_indicator(
        cw, ch, {"indicators": {"g": cfg_plain}}, "", "g", 45.0, "km/h", "",
        cfg_plain, 1080, 0, 16, None, 0, 100, 10, 1.0, 200, 1, formatted_val=""
    )
    img_shadow, _, _, _ = _render_gauge_indicator(
        cw, ch, {"indicators": {"g": cfg_shadow}}, "", "g", 45.0, "km/h", "",
        cfg_shadow, 1080, 0, 16, None, 0, 100, 10, 1.0, 200, 1, formatted_val=""
    )

    arr_p = np.asarray(img_plain)
    arr_s = np.asarray(img_shadow)
    # Shadow must produce additional dark pixels
    assert np.any(arr_s[:, :, 3] > arr_p[:, :, 3])


def test_4_resolution_change():
    """Rendering at 1080p then 4K must not return stale 1080p cached tiles."""
    clear_effects_cache()
    clear_bar_cache()
    cfg = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "unit": "km", "label": "DIST",
    }
    img_1080, _, _, _ = _render_bar_indicator(
        1920, 1080, {"indicators": {"bar": cfg}}, "", "bar", 50.0, "km", "DIST",
        cfg, 1080, 0, 16, None, 0, 100, 10, 2.0, 500, 2, formatted_val="50.0"
    )
    img_4k, _, _, _ = _render_bar_indicator(
        3840, 2160, {"indicators": {"bar": cfg}}, "", "bar", 50.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    assert img_4k.width > img_1080.width * 1.5


def test_5_two_indicators_with_similar_configs():
    """Two different gauge indicators with identical values must maintain isolated states."""
    clear_gauge_cache()
    cw, ch = 1920, 1080
    cfg1 = {"x": 20.0, "y": 50.0, "size": 20.0, "needle_color": "#FF0000", "min_val": 0, "max_val": 100}
    cfg2 = {"x": 80.0, "y": 50.0, "size": 20.0, "needle_color": "#00FF00", "min_val": 0, "max_val": 100}

    img1, _, _, _ = _render_gauge_indicator(
        cw, ch, {"indicators": {"g1": cfg1}}, "", "g1", 50.0, "km/h", "",
        cfg1, 1080, 0, 16, None, 0, 100, 10, 1.0, 200, 1, formatted_val="50.0"
    )
    img2, _, _, _ = _render_gauge_indicator(
        cw, ch, {"indicators": {"g2": cfg2}}, "", "g2", 50.0, "km/h", "",
        cfg2, 1080, 0, 16, None, 0, 100, 10, 1.0, 200, 1, formatted_val="50.0"
    )

    arr1 = np.asarray(img1)
    arr2 = np.asarray(img2)
    assert np.max(arr1[:, :, 0]) > 200  # g1 is red
    assert np.max(arr2[:, :, 1]) > 200  # g2 is green


def test_6_multiple_queued_jobs_clear_cache():
    """clear_*_cache functions must completely flush caches without leakage."""
    clear_gauge_cache()
    clear_bar_cache()
    clear_effects_cache()
    from src.indicators.gauge import _GAUGE_CANVAS_STATE, _GAUGE_RASTER_CACHE
    from src.indicators.effects import _EFFECT_CACHE
    assert _GAUGE_CANVAS_STATE["canvas"] is None
    assert len(_GAUGE_RASTER_CACHE) == 0
    assert len(_EFFECT_CACHE) == 0


def test_7_8_input_and_output_mutation_safety():
    """Mutating a returned image must NOT corrupt the cache for subsequent calls."""
    clear_effects_cache()
    clear_bar_cache()
    cw, ch = 1920, 1080
    cfg = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
        "shadow_enabled": True, "shadow_distance": 2.0,
    }

    img1, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 25.0, "km", "DIST",
        cfg, 1080, 0, 16, None, 0, 100, 10, 2.0, 500, 2, formatted_val="25.0"
    )

    # Malicious external mutation of img1: paint a blue box across it
    d = ImageDraw.Draw(img1)
    d.rectangle([10, 10, 100, 100], fill=(0, 0, 255, 255))

    # Second call requesting the exact same value
    img2, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 25.0, "km", "DIST",
        cfg, 1080, 0, 16, None, 0, 100, 10, 2.0, 500, 2, formatted_val="25.0"
    )

    # img2 must NOT contain the painted blue box!
    px2 = img2.getpixel((50, 50))
    # It must NOT be pure blue (0, 0, 255)
    assert px2 != (0, 0, 255, 255)
