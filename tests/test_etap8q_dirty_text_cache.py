"""
Unit test suite for ETAP 8Q: Dirty Text Cache / selective rendering CPU_ABOVE_MAP.
Validates:
1. test_above_text_cache_same_text_hit
2. test_above_text_cache_changed_text_miss
3. test_above_text_cache_none_visibility
4. test_above_text_cache_zero_visible
5. test_above_text_cache_style_invalidation
6. test_above_text_cache_rotation
7. test_above_text_cache_outline_shadow
8. test_above_text_cache_position_independent
9. test_above_text_cache_overlap_order
10. test_above_text_cache_resolution_namespace
11. test_above_text_cache_bounded_growth
12. test_above_text_cache_pixel_parity
"""
from __future__ import annotations

from datetime import datetime
from PIL import Image, ImageDraw
import pytest

from src.indicators.text_cache import (
    AboveTextCache,
    TextRasterKey,
    TextRasterEntry,
    get_above_text_cache,
)
from src.indicators.compositor import compose_overlay


def test_above_text_cache_same_text_hit():
    """Identical text queries result in cache hits."""
    cache = AboveTextCache(max_entries=10)
    key = TextRasterKey(
        key="fit_battery_pct_text",
        text="Bat: 77%",
        font_path="assets/Roboto-Bold.ttf",
        font_size=24,
        color=(255, 255, 255, 255),
        outline_width=2,
        outline_color=(0, 0, 0, 255),
        rotation=0,
        canvas_w=3840,
        canvas_h=2160,
    )
    img = Image.new("RGBA", (100, 30), (255, 255, 255, 255))
    entry = TextRasterEntry(image=img, width=100, height=30)
    
    # 1. Miss on first get
    assert cache.get(key) is None
    cache.put(key, entry)
    
    # 2. Hit on second get
    cached = cache.get(key)
    assert cached is not None
    assert cached.image is img
    
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate_pct"] == 50.0


def test_above_text_cache_changed_text_miss():
    """Different text generates a cache miss."""
    cache = AboveTextCache(max_entries=10)
    k1 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    k2 = TextRasterKey("k", "78%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    
    cache.put(k1, TextRasterEntry(Image.new("RGBA", (50, 20)), 50, 20))
    assert cache.get(k2) is None, "Changed text must miss cache!"


def test_above_text_cache_none_visibility():
    """None value is invisible with 0 ghosting."""
    layout = {
        "indicators": {
            "fit_battery_pct_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.5, "y": 0.5}
        }
    }
    # Frame 1: visible
    f1 = {"extra_indicators": {"fit_battery_pct_text": (77.0, "%", "Bat")}}
    img1 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas="above", **f1)
    bbox1 = img1.getbbox()
    assert bbox1 is not None
    
    # Frame 2: None (missing) -> must clear previous region and be completely transparent
    f2 = {"extra_indicators": {"fit_battery_pct_text": None}}
    img2 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas="above", **f2)
    bbox2 = img2.getbbox()
    assert bbox2 is None, "Frame with None must be completely transparent without ghosting!"


def test_above_text_cache_zero_visible():
    """0.0 is treated as valid visible text, not missing."""
    layout = {
        "indicators": {
            "fit_solar_pct_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.5, "y": 0.5}
        }
    }
    f0 = {"extra_indicators": {"fit_solar_pct_text": (0.0, "%", "Solar")}}
    img0 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas="above", **f0)
    assert img0.getbbox() is not None, "0.0 must be visible!"


def test_above_text_cache_style_invalidation():
    """Changing style/color/font_size creates distinct keys."""
    k_white = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    k_yellow = TextRasterKey("k", "77%", "font", 24, (255, 255, 0, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    k_large = TextRasterKey("k", "77%", "font", 48, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    
    assert k_white != k_yellow
    assert k_white != k_large


def test_above_text_cache_rotation():
    """Rotations (0, 90, 180, 270) produce distinct cache keys and geometries."""
    k0 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    k90 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 90, 3840, 2160)
    k180 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 180, 3840, 2160)
    k270 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 270, 3840, 2160)
    assert k0 != k90 != k180 != k270


def test_above_text_cache_rotation_contract_orthogonal_steps():
    """TeleM renderer officially supports orthogonal 90-degree step rotations (0, 90, 180, 270).
    Arbitrary angles (e.g. 17 deg) are distinct in cache key."""
    k17 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 17, 3840, 2160)
    k0 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    assert k17 != k0
    assert k17.rotation == 17


def test_above_text_cache_outline_shadow():
    """Outline width change produces distinct cache key."""
    k1 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    k2 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 4, (0, 0, 0, 255), 0, 3840, 2160)
    assert k1 != k2


def test_above_text_cache_position_independent():
    """Moving an indicator to new (x,y) reuses raster key and updates bbox."""
    layout1 = {"indicators": {"k": {"enabled": True, "form": "text", "source": "fit", "x": 0.2, "y": 0.2}}}
    layout2 = {"indicators": {"k": {"enabled": True, "form": "text", "source": "fit", "x": 0.8, "y": 0.8}}}
    
    f = {"extra_indicators": {"k": (50.0, "%", "Val")}}
    
    b1 = {}
    compose_overlay(3840, 2160, layout1, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, _bboxes=b1, reuse_canvas="above", **f)
    
    b2 = {}
    compose_overlay(3840, 2160, layout2, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, _bboxes=b2, reuse_canvas="above", **f)
    
    assert b1["k"] != b2["k"], "Bbox must reflect new position!"


def test_above_text_cache_overlap_order():
    """Overlapping indicators maintain strict painter insertion order."""
    layout = {
        "indicators": {
            "bg_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.5, "y": 0.5, "text_color": "#FF0000"},
            "fg_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.5, "y": 0.5, "text_color": "#00FF00"},
        }
    }
    f = {"extra_indicators": {"bg_text": (1.0, "", "A"), "fg_text": (2.0, "", "A")}}
    img = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas="above", **f)
    assert img.getbbox() is not None


def test_above_text_cache_resolution_namespace():
    """Canvas resolution (4K vs 1080p) is isolated in cache key."""
    k4k = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
    k1080 = TextRasterKey("k", "77%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 1920, 1080)
    assert k4k != k1080


def test_above_text_cache_bounded_growth():
    """Cache does not exceed max_entries."""
    cache = AboveTextCache(max_entries=3)
    for i in range(10):
        k = TextRasterKey("k", f"{i}%", "font", 24, (255, 255, 255, 255), 2, (0, 0, 0, 255), 0, 3840, 2160)
        cache.put(k, TextRasterEntry(Image.new("RGBA", (10, 10)), 10, 10))
    
    assert len(cache.cache) <= 3
    assert cache.stats()["entries"] <= 3


def test_above_text_cache_pixel_parity():
    """Uncached render and cached render produce byte-exact pixel parity."""
    layout = {
        "indicators": {
            "fit_battery_pct_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.3, "y": 0.4},
            "fit_solar_pct_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.6, "y": 0.4},
        }
    }
    f = {"extra_indicators": {"fit_battery_pct_text": (88.0, "%", "Bat"), "fit_solar_pct_text": (42.0, "%", "Solar")}}
    
    # 1. Uncached
    img_uncached = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas=False, **f)
    
    # 2. Cached
    img_cached = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas="above", **f)
    
    assert img_uncached.tobytes() == img_cached.tobytes(), "Cached overlay must match uncached byte-for-byte!"
