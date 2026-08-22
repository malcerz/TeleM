from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from PIL import Image

from src.indicators.time_display import render_time_display, _LINE_TILE_CACHE, _ICON_CACHE, _TEXT_METRIC_CACHE
from src.indicators.helpers import _STATIC_CACHE, resolve_indicator_font_path


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATH = ROOT / "presets" / "cycling_dashboard_v10.json"


def _load_layout():
    with open(LAYOUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_time_display_cache_hit_parity():
    """Verify that second call (cache hit) returns identical image and placement."""
    layout = _load_layout()
    _STATIC_CACHE.clear()
    _LINE_TILE_CACHE.clear()

    img1, x1, y1 = render_time_display(1280, 720, layout, "", "2026.08.14", "11:18:10", 10.0, 25.0)
    img2, x2, y2 = render_time_display(1280, 720, layout, "", "2026.08.14", "11:18:10", 10.0, 25.0)

    assert x1 == x2 and y1 == y2
    assert np.array_equal(np.array(img1), np.array(img2))


def test_time_display_dynamic_changes():
    """Verify changes in time, date, elapsed, and avg speed produce distinct images."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    base_img, _, _ = render_time_display(1280, 720, layout, "", "2026.08.14", "11:18:10", 10.0, 25.0)
    base_arr = np.array(base_img)

    # Time change
    img_time, _, _ = render_time_display(1280, 720, layout, "", "2026.08.14", "11:18:11", 10.0, 25.0)
    assert not np.array_equal(base_arr, np.array(img_time))

    # Date change
    img_date, _, _ = render_time_display(1280, 720, layout, "", "2026.08.15", "11:18:10", 10.0, 25.0)
    assert not np.array_equal(base_arr, np.array(img_date))

    # Elapsed change
    img_el, _, _ = render_time_display(1280, 720, layout, "", "2026.08.14", "11:18:10", 11.0, 25.0)
    assert not np.array_equal(base_arr, np.array(img_el))

    # Avg speed change
    img_spd, _, _ = render_time_display(1280, 720, layout, "", "2026.08.14", "11:18:10", 10.0, 28.5)
    assert not np.array_equal(base_arr, np.array(img_spd))


def test_time_display_font_invalidation():
    """Verify switching fonts produces distinct rasters and switching back restores exact match."""
    layout = _load_layout()
    _STATIC_CACHE.clear()

    img_def1, _, _ = render_time_display(1280, 720, layout, "", "2026.08.14", "11:18:10", 10.0, 25.0)

    fpath_dig = resolve_indicator_font_path("Digital-7", "")
    if fpath_dig:
        img_dig, _, _ = render_time_display(1280, 720, layout, fpath_dig, "2026.08.14", "11:18:10", 10.0, 25.0)
        assert not np.array_equal(np.array(img_def1), np.array(img_dig))

    # Switch back to default
    img_def2, _, _ = render_time_display(1280, 720, layout, "", "2026.08.14", "11:18:10", 10.0, 25.0)
    assert np.array_equal(np.array(img_def1), np.array(img_def2))


def test_time_display_bounded_caches():
    """Verify bounded caches do not grow unbounded over many different frames."""
    layout = _load_layout()
    _STATIC_CACHE.clear()
    _LINE_TILE_CACHE.clear()

    for i in range(200):
        t_sec = float(i)
        render_time_display(1280, 720, layout, "", "2026.08.14", f"11:18:{i%60:02d}", t_sec, 20.0 + (i%10))

    assert len(_LINE_TILE_CACHE) <= _LINE_TILE_CACHE.max_entries
    assert len(_STATIC_CACHE) <= _STATIC_CACHE.max_entries


def test_time_display_disabled_and_empty_fields():
    """Verify disabled layout and empty strings return (None, 0, 0)."""
    layout = _load_layout()
    layout_disabled = json.loads(json.dumps(layout))
    layout_disabled["indicators"]["time_display"]["enabled"] = False
    res, x, y = render_time_display(1280, 720, layout_disabled, "", "2026.08.14", "11:18:10", 10.0, 25.0)
    assert res is None and x == 0 and y == 0
