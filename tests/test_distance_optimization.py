from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from PIL import Image

from src.indicators.bar import _render_ruler, _RULER_METRICS_CACHE
from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import _STATIC_CACHE, resolve_indicator_font_path, s


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATH = ROOT / "presets" / "cycling_dashboard_v10.json"


def _load_layout():
    with open(LAYOUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_distance_cache_hit_parity():
    """Verify that second call (cache hit) returns identical image and placement."""
    layout = _load_layout()
    _STATIC_CACHE.clear()
    _RULER_METRICS_CACHE.clear()

    cfg = layout["indicators"]["dist_visual"]
    img1, x1, y1, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 5.2, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="5.2 km", supersample=1
    )
    img2, x2, y2, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 5.2, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="5.2 km", supersample=1
    )
    assert x1 == x2 and y1 == y2
    assert np.array_equal(np.array(img1), np.array(img2))


def test_distance_dynamic_marker_and_value():
    """Verify changes in distance value update marker and raster distinctly."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    cfg = layout["indicators"]["dist_visual"]
    img_low, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 1.0, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="1.0 km", supersample=1
    )
    img_low = img_low.copy()
    img_mid, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 5.0, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="5.0 km", supersample=1
    )
    img_mid = img_mid.copy()
    img_high, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 9.5, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="9.5 km", supersample=1
    )
    img_high = img_high.copy()

    assert not np.array_equal(np.array(img_low), np.array(img_mid))
    assert not np.array_equal(np.array(img_mid), np.array(img_high))


def test_distance_none_behavior():
    """Verify that value=None renders cleanly without marker and with '--' value."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    cfg = layout["indicators"]["dist_visual"]
    img_val, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 0.0, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="0.0 km", supersample=1
    )
    img_val = img_val.copy()
    img_none, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", None, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="--", supersample=1
    )
    img_none = img_none.copy()

    assert not np.array_equal(np.array(img_val), np.array(img_none))


def test_distance_font_invalidation():
    """Verify font switching produces distinct raster and restores cleanly."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    cfg = layout["indicators"]["dist_visual"]
    img_def1, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 4.2, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="4.2 km", supersample=1
    )

    fpath_dig = resolve_indicator_font_path("Digital-7", "")
    if fpath_dig:
        img_dig, _, _, _ = render_value_indicator(
            1280, 720, layout, fpath_dig, "dist_visual", 4.2, "km", cfg.get("label", ""),
            cfg_override=cfg, formatted_val="4.2 km", supersample=1
        )
        assert not np.array_equal(np.array(img_def1), np.array(img_dig))

    img_def2, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 4.2, "km", cfg.get("label", ""),
        cfg_override=cfg, formatted_val="4.2 km", supersample=1
    )
    assert np.array_equal(np.array(img_def1), np.array(img_def2))


def test_distance_pixel_profile_toggle():
    """Verify pixel profile setting modifies ruler geometry compared to default profile."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    cfg_pix = layout["indicators"]["dist_visual"]
    cfg_def = json.loads(json.dumps(cfg_pix))
    cfg_def["tick_profile"] = "default"

    img_pix, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 5.0, "km", cfg_pix.get("label", ""),
        cfg_override=cfg_pix, formatted_val="5.0 km", supersample=1
    )
    img_def, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "dist_visual", 5.0, "km", cfg_def.get("label", ""),
        cfg_override=cfg_def, formatted_val="5.0 km", supersample=1
    )

    assert not np.array_equal(np.array(img_pix), np.array(img_def))


def test_distance_bounded_caches():
    """Verify caches remain bounded under heavy distinct value iterations."""
    layout = _load_layout()
    _STATIC_CACHE.clear()
    _RULER_METRICS_CACHE.clear()

    cfg = layout["indicators"]["dist_visual"]
    for i in range(200):
        val = float(i % 100) * 0.1
        render_value_indicator(
            1280, 720, layout, "", "dist_visual", val, "km", cfg.get("label", ""),
            cfg_override=cfg, formatted_val=f"{val:.1f} km", supersample=1
        )

    assert len(_RULER_METRICS_CACHE) <= 256
    assert len(_STATIC_CACHE) <= _STATIC_CACHE.max_entries
