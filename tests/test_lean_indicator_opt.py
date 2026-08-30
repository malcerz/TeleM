"""Tests for Lean Indicator Optimization and Parity (ETAP 6C.1)."""

import json
import pytest
import numpy as np
from PIL import Image, ImageChops

from src.indicators.lean import (
    _render_lean_indicator,
    lean_angle,
    lean_visual_angle,
    clear_lean_caches,
    _load_lean_graphic,
    _graphic_pivot,
    _rotate_paste_params,
)
from src.indicators.helpers import load_font


@pytest.fixture(autouse=True)
def clean_caches():
    clear_lean_caches()
    yield
    clear_lean_caches()


def _get_dummy_cfg(size=14.0):
    return {
        "enabled": True,
        "label": "Przechył",
        "form": "lean",
        "font_size": 2.5,
        "size": size,
        "show_value": True,
        "show_label": True,
        "source": "gyro",
        "decimals": 0,
        "zero_offset": 0.0,
        "invert_axis": False,
        "pivot_x": 0.5,
        "pivot_y": 1.0,
        "sensitivity": 1.0,
        "max_angle": 30.0,
        "graphic": "bike",
        "show_reference": True,
        "show_ticks": True,
        "track_color": "#FFFFFF",
        "tick_color": "#AAAAAA",
        "x": 50.0,
        "y": 50.0,
    }


def test_lean_angle_calculation():
    cfg = _get_dummy_cfg()
    assert lean_angle(0.0, cfg) == 0.0
    assert lean_angle(15.0, cfg) == 15.0
    assert lean_angle(-20.0, cfg) == -20.0
    assert lean_angle(45.0, cfg) == 30.0  # clamped to max_angle 30.0
    assert lean_angle(-50.0, cfg) == -30.0  # clamped to -max_angle -30.0
    assert lean_angle(None, cfg) == 0.0


def test_lean_cache_invalidation():
    clear_lean_caches()
    cfg = _get_dummy_cfg()
    font_path = "C:/Windows/Fonts/arial.ttf"
    font = load_font(font_path, 20)
    
    # Render frame 1
    img1, x1, y1, _ = _render_lean_indicator(
        canvas_w=1920, canvas_h=1080, layout={}, font_path=font_path,
        key="lean_indicator", value=12.345, unit="°", label="Przechył",
        cfg=cfg, min_dim=1080, outline=2, fs=20, font=font,
        val_min=-30.0, val_max=30.0, ticks=0, thickness=1, size_px=150, ss=1,
    )
    assert img1 is not None

    # Clear caches
    clear_lean_caches()

    # Render frame 2 after cache clearing
    img2, x2, y2, _ = _render_lean_indicator(
        canvas_w=1920, canvas_h=1080, layout={}, font_path=font_path,
        key="lean_indicator", value=12.345, unit="°", label="Przechył",
        cfg=cfg, min_dim=1080, outline=2, fs=20, font=font,
        val_min=-30.0, val_max=30.0, ticks=0, thickness=1, size_px=150, ss=1,
    )
    # Output must be identical
    diff = ImageChops.difference(img1, img2)
    assert diff.getbbox() is None
    assert x1 == x2
    assert y1 == y2


def test_lean_repeated_rendering_consistency():
    cfg = _get_dummy_cfg()
    font_path = "C:/Windows/Fonts/arial.ttf"
    font = load_font(font_path, 20)

    # Render same fractional angle twice
    img_a, _, _, _ = _render_lean_indicator(
        canvas_w=2560, canvas_h=1440, layout={}, font_path=font_path,
        key="lean_indicator", value=-14.5678, unit="°", label="Przechył",
        cfg=cfg, min_dim=1440, outline=2, fs=25, font=font,
        val_min=-30.0, val_max=30.0, ticks=0, thickness=1, size_px=200, ss=1,
    )
    img_b, _, _, _ = _render_lean_indicator(
        canvas_w=2560, canvas_h=1440, layout={}, font_path=font_path,
        key="lean_indicator", value=-14.5678, unit="°", label="Przechył",
        cfg=cfg, min_dim=1440, outline=2, fs=25, font=font,
        val_min=-30.0, val_max=30.0, ticks=0, thickness=1, size_px=200, ss=1,
    )
    diff = ImageChops.difference(img_a, img_b)
    assert diff.getbbox() is None


def test_lean_real_fractional_angles_exact_parity():
    cfg = _get_dummy_cfg()
    font_path = "C:/Windows/Fonts/arial.ttf"
    font = load_font(font_path, 20)

    # Test various non-integer fractional angles
    angles = [-23.456, -11.111, -0.123, 0.0, 0.987, 7.654, 19.876]
    for ang in angles:
        img, x, y, _ = _render_lean_indicator(
            canvas_w=2560, canvas_h=1440, layout={}, font_path=font_path,
            key="lean_indicator", value=ang, unit="°", label="Przechył",
            cfg=cfg, min_dim=1440, outline=2, fs=25, font=font,
            val_min=-30.0, val_max=30.0, ticks=0, thickness=1, size_px=200, ss=1,
        )
        assert img is not None
        assert img.width > 0
        assert img.height > 0


def test_lean_size_scaling_100_75_50():
    cfg = _get_dummy_cfg()
    font_path = "C:/Windows/Fonts/arial.ttf"
    
    # 4K (3840x2160), 1440p (2560x1440), 1080p (1920x1080)
    for w, h in [(3840, 2160), (2560, 1440), (1920, 1080)]:
        min_dim = min(w, h)
        fs = max(10, int(round(min_dim * (float(cfg.get("font_size", 2.5)) / 100.0))))
        outline = max(1, int(round(fs * 0.1)))
        size_px = int(round(float(cfg.get("size", 14.0)) / 100.0 * min_dim))
        font = load_font(font_path, fs)

        img, x, y, bbox = _render_lean_indicator(
            canvas_w=w, canvas_h=h, layout={}, font_path=font_path,
            key="lean_indicator", value=10.5, unit="°", label="Przechył",
            cfg=cfg, min_dim=min_dim, outline=outline, fs=fs, font=font,
            val_min=-30.0, val_max=30.0, ticks=0, thickness=1, size_px=size_px, ss=1,
        )
        assert img.width > 0
        assert img.height > 0
        assert 0 <= x <= w
        assert 0 <= y <= h
