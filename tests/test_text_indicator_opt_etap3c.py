import pytest
import numpy as np
from PIL import Image, ImageDraw

from src.indicators.text import (
    _render_text_indicator,
    get_text_cache_stats,
    clear_text_cache,
    _TEXT_INDICATOR_CACHE,
)
from src.indicators.helpers import load_font


def test_text_indicator_cache_hit_and_stats():
    clear_text_cache()
    layout = {"indicators": {"iso_text": {"x": 5.0, "y": 50.0, "icon": "none"}}}
    cfg = layout["indicators"]["iso_text"]

    # First call: cache miss
    res1 = _render_text_indicator(
        canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
        key="iso_text", value=400, unit="", label="ISO",
        cfg=cfg, min_dim=2160, outline=2, fs=36, font=None,
        val_min=0, val_max=6400, ticks=0, thickness=2, size_px=100, ss=1,
        formatted_val="ISO: 400"
    )
    assert res1[0] is not None
    stats1 = get_text_cache_stats()
    assert stats1["entries"] == 1
    assert stats1["misses"] == 1
    assert stats1["hits"] == 0

    # Second call with identical string: cache hit
    res2 = _render_text_indicator(
        canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
        key="iso_text", value=400, unit="", label="ISO",
        cfg=cfg, min_dim=2160, outline=2, fs=36, font=None,
        val_min=0, val_max=6400, ticks=0, thickness=2, size_px=100, ss=1,
        formatted_val="ISO: 400"
    )
    # Should return identical object from cache
    assert res1[0] is res2[0]
    stats2 = get_text_cache_stats()
    assert stats2["entries"] == 1
    assert stats2["misses"] == 1
    assert stats2["hits"] == 1
    assert stats2["hit_rate_pct"] == 50.0


def test_text_indicator_eviction_bounded():
    clear_text_cache()
    layout = {"indicators": {"test_txt": {"x": 10.0, "y": 10.0, "icon": "none"}}}
    cfg = layout["indicators"]["test_txt"]

    # Insert 600 unique entries into a 512-entry cache
    for i in range(600):
        _render_text_indicator(
            canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
            key="test_txt", value=i, unit="units", label=f"Label_{i}",
            cfg=cfg, min_dim=2160, outline=2, fs=24, font=None,
            val_min=0, val_max=1000, ticks=0, thickness=2, size_px=100, ss=1,
            formatted_val=f"Value {i}"
        )

    stats = get_text_cache_stats()
    assert stats["entries"] <= 512
    assert len(_TEXT_INDICATOR_CACHE) <= 512


def test_text_indicator_sensitivity():
    clear_text_cache()
    layout = {"indicators": {"t1": {"x": 10.0, "y": 10.0, "icon": "none", "text_color": "#FF0000"}}}
    cfg1 = layout["indicators"]["t1"]
    cfg2 = {"x": 10.0, "y": 10.0, "icon": "none", "text_color": "#00FF00"}

    # Different text color should produce distinct cache entries
    r1 = _render_text_indicator(
        canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
        key="t1", value=10, unit="", label="T",
        cfg=cfg1, min_dim=2160, outline=2, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=2, size_px=100, ss=1,
        formatted_val="T: 10"
    )
    r2 = _render_text_indicator(
        canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
        key="t1", value=10, unit="", label="T",
        cfg=cfg2, min_dim=2160, outline=2, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=2, size_px=100, ss=1,
        formatted_val="T: 10"
    )
    assert r1[0] is not r2[0]
    assert len(_TEXT_INDICATOR_CACHE) == 2


def test_text_indicator_edge_cases():
    layout = {"indicators": {"empty": {"x": 10.0, "y": 10.0, "icon": "none"}}}
    cfg = layout["indicators"]["empty"]

    # Empty string should safely return None
    r = _render_text_indicator(
        canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
        key="empty", value=None, unit="", label="",
        cfg=cfg, min_dim=2160, outline=2, fs=24, font=None,
        val_min=0, val_max=100, ticks=0, thickness=2, size_px=100, ss=1,
        formatted_val=""
    )
    assert r[0] is None
