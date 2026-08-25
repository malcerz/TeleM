from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from PIL import Image

from src.indicators.bar import _render_segments, _SEG_BASE_CACHE, _SEG_ACTIVE_CACHE, _SEG_ICON_CACHE
from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import _STATIC_CACHE, resolve_indicator_font_path, s


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATH = ROOT / "presets" / "cycling_dashboard_v10.json"


def _load_layout():
    with open(LAYOUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_battery_solar_cache_hit_parity():
    """Verify that second call (cache hit) returns identical image and placement."""
    layout = _load_layout()
    _STATIC_CACHE.clear()
    _SEG_BASE_CACHE.clear()
    _SEG_ACTIVE_CACHE.clear()

    for key in ["fit_battery_pct_text", "fit_solar_pct_text"]:
        cfg = layout["indicators"][key]
        img1, x1, y1, _ = render_value_indicator(
            1280, 720, layout, "", key, 85.0, "%", cfg.get("label", ""),
            cfg_override=cfg, formatted_val="85%", supersample=1
        )
        img2, x2, y2, _ = render_value_indicator(
            1280, 720, layout, "", key, 85.0, "%", cfg.get("label", ""),
            cfg_override=cfg, formatted_val="85%", supersample=1
        )
        assert x1 == x2 and y1 == y2
        assert np.array_equal(np.array(img1), np.array(img2))


def test_battery_solar_zero_vs_none_semantics():
    """Verify that value=0.0 and value=None produce distinct rasters."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    for key in ["fit_battery_pct_text", "fit_solar_pct_text"]:
        cfg = layout["indicators"][key]
        img_zero, _, _, _ = render_value_indicator(
            1280, 720, layout, "", key, 0.0, "%", cfg.get("label", ""),
            cfg_override=cfg, formatted_val="0%", supersample=1
        )
        img_none, _, _, _ = render_value_indicator(
            1280, 720, layout, "", key, None, "%", cfg.get("label", ""),
            cfg_override=cfg, formatted_val="--", supersample=1
        )
        assert not np.array_equal(np.array(img_zero), np.array(img_none))


def test_battery_solar_dynamic_sequence():
    """Verify dynamic step sequence produces distinct output on each step."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    cfg_bat = layout["indicators"]["fit_battery_pct_text"]
    bat_seq = [89.0, 88.0, 50.0, 0.0, None, 100.0]
    prev_arr = None
    for val in bat_seq:
        fv = f"{int(val)}%" if val is not None else "--"
        img, _, _, _ = render_value_indicator(
            1280, 720, layout, "", "fit_battery_pct_text", val, "%", cfg_bat.get("label", ""),
            cfg_override=cfg_bat, formatted_val=fv, supersample=1
        )
        arr = np.array(img)
        if prev_arr is not None:
            assert arr.shape != prev_arr.shape or not np.array_equal(arr, prev_arr)
        prev_arr = arr


def test_battery_solar_font_invalidation():
    """Verify font change generates distinct rasters and switching back restores exact match."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    cfg = layout["indicators"]["fit_battery_pct_text"]
    img_def1, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "fit_battery_pct_text", 85.0, "%", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="85%", supersample=1
    )

    fpath_dig = resolve_indicator_font_path("Digital-7", "")
    if fpath_dig:
        img_dig, _, _, _ = render_value_indicator(
            1280, 720, layout, fpath_dig, "fit_battery_pct_text", 85.0, "%", cfg.get("label", ""),
            cfg_override=cfg, formatted_val="85%", supersample=1
        )
        assert not np.array_equal(np.array(img_def1), np.array(img_dig))

    img_def2, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "fit_battery_pct_text", 85.0, "%", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="85%", supersample=1
    )
    assert np.array_equal(np.array(img_def1), np.array(img_def2))


def test_battery_solar_bounded_caches():
    """Verify caches remain bounded under heavy distinct value iterations."""
    layout = _load_layout()
    _STATIC_CACHE.clear()
    _SEG_BASE_CACHE.clear()
    _SEG_ACTIVE_CACHE.clear()

    cfg = layout["indicators"]["fit_battery_pct_text"]
    for i in range(200):
        val = float(i % 101)
        render_value_indicator(
            1280, 720, layout, "", "fit_battery_pct_text", val, "%", cfg.get("label", ""),
            cfg_override=cfg, formatted_val=f"{int(val)}%", supersample=1
        )

    assert len(_SEG_BASE_CACHE) <= _SEG_BASE_CACHE.max_entries
    assert len(_SEG_ACTIVE_CACHE) <= _SEG_ACTIVE_CACHE.max_entries
    assert len(_STATIC_CACHE) <= _STATIC_CACHE.max_entries


def test_battery_and_solar_isolation():
    """Verify Battery and Solar widgets remain isolated and don't overwrite each other's base layers."""
    layout = _load_layout()
    _STATIC_CACHE.clear()
    _SEG_BASE_CACHE.clear()

    bat_cfg = layout["indicators"]["fit_battery_pct_text"]
    sol_cfg = layout["indicators"]["fit_solar_pct_text"]

    bat_img, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "fit_battery_pct_text", 50.0, "%", bat_cfg.get("label", ""),
        cfg_override=bat_cfg, formatted_val="50%", supersample=1
    )
    sol_img, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "fit_solar_pct_text", 50.0, "%", sol_cfg.get("label", ""),
        cfg_override=sol_cfg, formatted_val="50%", supersample=1
    )

    # Battery has 20 segments, Solar has 10 segments -> rasters must differ
    assert not np.array_equal(np.array(bat_img), np.array(sol_img))
