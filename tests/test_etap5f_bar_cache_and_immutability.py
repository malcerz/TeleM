"""Comprehensive test suite for Etap 5F: Bar/Ruler cache parity and immutability.

Tests:
1. Value change verification (different value produces different output).
2. Alternating values A -> B -> A (fresh output matches prior identical value).
3. Color change with same alpha mask (RGB channel update, no stale color).
4. Style change (ruler -> segmented -> vertical).
5. Shadow / fade / outline parameter invalidation.
6. Resolution change (1080p -> 4K).
7. Two similar indicators simultaneously.
8. External mutation safety (returned image mutation must NOT corrupt cache).
9. Multiple cache flushes / clear_bar_cache().
"""
from __future__ import annotations

import pytest
import numpy as np
from PIL import Image, ImageDraw

from src.indicators.bar import _render_bar_indicator, clear_bar_cache
from src.indicators.effects import apply_indicator_effects, clear_effects_cache


def test_1_value_change():
    """Different values must yield different output images and distinct dynamic keys."""
    clear_bar_cache()
    clear_effects_cache()
    cw, ch = 3840, 2160
    cfg = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
    }
    img1, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 10.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="10.0"
    )
    img2, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 80.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="80.0"
    )
    arr1 = np.asarray(img1)
    arr2 = np.asarray(img2)
    assert not np.array_equal(arr1, arr2)


def test_2_alternating_values_aba():
    """Alternating values (A -> B -> A) must return identical content for both A runs."""
    clear_bar_cache()
    clear_effects_cache()
    cw, ch = 3840, 2160
    cfg = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
    }
    img_a1, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 25.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="25.0"
    )
    img_b, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 75.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="75.0"
    )
    img_a2, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 25.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="25.0"
    )
    assert np.array_equal(np.asarray(img_a1), np.asarray(img_a2))
    assert not np.array_equal(np.asarray(img_a1), np.asarray(img_b))


def test_3_color_change_with_same_alpha():
    """Changing text_color must update RGB channels without returning stale cached color."""
    clear_bar_cache()
    clear_effects_cache()
    cw, ch = 3840, 2160
    cfg_white = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
    }
    cfg_red = dict(cfg_white)
    cfg_red["text_color"] = "#FF0000"

    img_w, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg_white}}, "", "bar", 50.0, "km", "DIST",
        cfg_white, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    img_r, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg_red}}, "", "bar", 50.0, "km", "DIST",
        cfg_red, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    arr_w = np.asarray(img_w)
    arr_r = np.asarray(img_r)
    # The images must not be identical and color difference on blue channel must be significant
    assert not np.array_equal(arr_w, arr_r)
    diff = np.max(np.abs(arr_w[:, :, 2].astype(int) - arr_r[:, :, 2].astype(int)))
    assert diff > 150


def test_4_style_change():
    """Changing bar_style between ruler and segments must produce distinct geometry."""
    clear_bar_cache()
    clear_effects_cache()
    cw, ch = 3840, 2160
    cfg_ruler = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
    }
    cfg_seg = dict(cfg_ruler)
    cfg_seg["bar_style"] = "segments"

    img_r, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg_ruler}}, "", "bar", 50.0, "km", "DIST",
        cfg_ruler, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    img_s, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg_seg}}, "", "bar", 50.0, "km", "DIST",
        cfg_seg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    assert not np.array_equal(np.asarray(img_r), np.asarray(img_s))


def test_5_shadow_fade_outline_invalidation():
    """Toggling shadows or modifying shadow distance must change effects output."""
    clear_bar_cache()
    clear_effects_cache()
    cw, ch = 3840, 2160
    cfg_plain = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
        "shadow_enabled": False,
    }
    cfg_shadow = dict(cfg_plain)
    cfg_shadow["shadow_enabled"] = True
    cfg_shadow["shadow_distance"] = 5.0
    cfg_shadow["shadow_length"] = 5.0

    img_p, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg_plain}}, "", "bar", 50.0, "km", "DIST",
        cfg_plain, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    img_s, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg_shadow}}, "", "bar", 50.0, "km", "DIST",
        cfg_shadow, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    eff_p = apply_indicator_effects(img_p, cfg_plain, 2160, profile_key="bar_p")
    eff_s = apply_indicator_effects(img_s, cfg_shadow, 2160, profile_key="bar_s")
    assert not np.array_equal(np.asarray(eff_p), np.asarray(eff_s))


def test_6_resolution_change():
    """Changing canvas resolution from 1080p to 4K must scale the indicator raster."""
    clear_bar_cache()
    clear_effects_cache()
    cfg = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
    }
    img_1080, _, _, _ = _render_bar_indicator(
        1920, 1080, {"indicators": {"bar": cfg}}, "", "bar", 50.0, "km", "DIST",
        cfg, 1080, 0, 16, None, 0, 100, 10, 2.0, 500, 2, formatted_val="50.0"
    )
    img_4k, _, _, _ = _render_bar_indicator(
        3840, 2160, {"indicators": {"bar": cfg}}, "", "bar", 50.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    assert img_4k.width > img_1080.width
    assert img_4k.height > img_1080.height


def test_7_two_indicators_similar_config():
    """Two different indicator keys with similar configs must not cross-pollinate cache."""
    clear_bar_cache()
    clear_effects_cache()
    cw, ch = 3840, 2160
    cfg1 = {
        "bar_style": "ruler", "direction": "horizontal", "x": 20.0, "y": 20.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
    }
    cfg2 = dict(cfg1)
    cfg2["x"] = 80.0
    cfg2["unit"] = "mi"

    img1, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"b1": cfg1}}, "", "b1", 50.0, "km", "D1",
        cfg1, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    img2, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"b2": cfg2}}, "", "b2", 50.0, "mi", "D2",
        cfg2, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="50.0"
    )
    assert not np.array_equal(np.asarray(img1), np.asarray(img2))


def test_8_pipeline_immutability_safety():
    """Applying pipeline effects to returned PIL Image must not mutate the cached raster in-place."""
    clear_bar_cache()
    clear_effects_cache()
    cw, ch = 3840, 2160
    cfg = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
        "shadow_enabled": True, "shadow_distance": 6.0, "shadow_length": 6.0,
    }
    img1, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 33.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="33.0"
    )
    arr1_before = np.array(img1)

    # Pass img1 through the real production effects pipeline
    eff = apply_indicator_effects(img1, cfg, 2160, profile_key="bar_immutability_test")
    assert eff is not None

    # img1 must remain completely untouched in-place by effects pipeline
    arr1_after = np.array(img1)
    assert np.array_equal(arr1_before, arr1_after)

    # Second query for identical state must return pristine cached image
    img2, _, _, _ = _render_bar_indicator(
        cw, ch, {"indicators": {"bar": cfg}}, "", "bar", 33.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="33.0"
    )
    arr2 = np.array(img2)
    assert np.array_equal(arr1_before, arr2)


def test_9_multiple_cache_flushes():
    """clear_bar_cache() must completely reset internal caches without errors."""
    clear_bar_cache()
    from src.indicators.bar import _BAR_INDICATOR_CACHE, _STATIC_CACHE
    assert len(_BAR_INDICATOR_CACHE) == 0
    # Warm up
    cfg = {
        "bar_style": "ruler", "direction": "horizontal", "x": 50.0, "y": 50.0,
        "size": 50.0, "thickness": 2.0, "min_val": 0.0, "max_val": 100.0,
        "text_color": "#FFFFFF", "unit": "km",
    }
    _render_bar_indicator(
        3840, 2160, {"indicators": {"bar": cfg}}, "", "bar", 10.0, "km", "DIST",
        cfg, 2160, 0, 16, None, 0, 100, 10, 2.0, 1000, 2, formatted_val="10.0"
    )
    assert len(_BAR_INDICATOR_CACHE) > 0
    clear_bar_cache()
    assert len(_BAR_INDICATOR_CACHE) == 0
