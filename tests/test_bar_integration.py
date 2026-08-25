"""Tests for unified bar indicator module (ruler + segments).

Validates:
- form='bar' with bar_style='ruler' (default)
- form='bar' with bar_style='segments'
- backward compatibility: form='segment_bar'
- rotation handling (0, 90, 180, 270 degrees)
- indicator values clamp / progression (0%, 1%, 25%, 50%, 75%, 100%, out-of-bounds)
- HUD bounding box calculation safety (zero clipping)
- preview and compositor integration
"""

import pytest
import numpy as np
from PIL import Image

from src.indicators.bar import _render_bar_indicator
from src.indicators.dispatcher import render_value_indicator
from src.indicators.compositor import compose_overlay, rotated_paste
from src.indicators.segment_bar import _render_segment_bar_indicator
from src.ffmpeg.command_builder import get_layout_hud_bbox
from src.gui.layout_manager import normalize_layout


def test_bar_ruler_default_rendering():
    """Test standard ruler style rendering."""
    layout = normalize_layout(None, 1920, 1080)
    cfg = {
        "enabled": True,
        "label": "Distance",
        "x": 50.0,
        "y": 80.0,
        "rotation": 0,
        "form": "bar",
        "bar_style": "ruler",
        "size": 25.0,
        "min_val": 0,
        "max_val": 100,
        "major_ticks": 8,
        "minor_ticks": 5,
        "show_range_labels": True,
        "show_value": True,
        "show_mid_label": True,
        "show_label": True,
    }
    img, rx, ry, extra = _render_bar_indicator(
        1920, 1080, layout, "", "dist_visual", 45.0, "km", "Distance",
        cfg, 1080, 2, 24, None, 0, 100, 8, 3, int(0.25 * 1920), 1
    )
    assert img is not None
    assert img.width > 0 and img.height > 0
    assert rx == int(0.50 * 1920)
    assert ry == int(0.80 * 1080)
    assert extra is None  # Local raster rendering, no outer annotations to duplicate


def test_bar_segments_rendering():
    """Test segmented style rendering across different values."""
    layout = normalize_layout(None, 1920, 1080)
    cfg = {
        "enabled": True,
        "label": "Battery",
        "x": 50.0,
        "y": 50.0,
        "rotation": 0,
        "form": "bar",
        "bar_style": "segments",
        "size": 20.0,
        "min_val": 0,
        "max_val": 100,
        "segments": 20,
        "segment_gap": 3,
        "segment_radius": 2,
        "inactive_alpha": 90,
        "grow_height": True,
        "grow_start": 0.5,
        "show_value": True,
        "show_label": True,
        "show_min": True,
        "show_max": True,
    }

    test_values = [0, 1, 25, 50, 75, 100, -15, 130]
    for v in test_values:
        img, sx, sy, extra = _render_bar_indicator(
            1920, 1080, layout, "", "battery", v, "%", "Battery",
            cfg, 1080, 2, 24, None, 0, 100, 0, 3, int(0.20 * 1920), 1
        )
        assert img is not None
        assert img.width > 0 and img.height > 0
        assert sx == int(0.50 * 1920)
        assert sy == int(0.50 * 1080)
        assert extra is None


def test_legacy_segment_bar_compatibility():
    """Test that legacy form='segment_bar' is automatically dispatched to bar.py segments."""
    layout = normalize_layout(None, 1920, 1080)
    legacy_cfg = {
        "enabled": True,
        "label": "Solar",
        "x": 30.0,
        "y": 40.0,
        "form": "segment_bar",
        "size": 15.0,
        "min_val": 0,
        "max_val": 100,
        "segments": 10,
    }
    layout["indicators"]["solar"] = legacy_cfg

    # 1. Via dispatcher
    img_disp, dx, dy, extra_disp = render_value_indicator(
        1920, 1080, layout, "", "solar", 60.0, "W", "Solar",
        cfg_override=legacy_cfg
    )
    assert img_disp is not None
    assert img_disp.width > 0

    # 2. Via legacy shim function
    img_shim, sx, sy, extra_shim = _render_segment_bar_indicator(
        1920, 1080, layout, "", "solar", 60.0, "W", "Solar",
        legacy_cfg, 1080, 2, 24, None, 0, 100, 0, 3, int(0.15 * 1920), 1
    )
    assert img_shim is not None


@pytest.mark.parametrize("style", ["ruler", "segments"])
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_bar_rotation_and_bbox_no_clipping(style, rot):
    """Test all rotation angles and verify bounding box covers all pixels with zero clipping."""
    layout = normalize_layout(None, 1920, 1080)
    cfg = {
        "enabled": True,
        "label": f"Test_{style}",
        "x": 50.0,
        "y": 50.0,
        "rotation": rot,
        "form": "bar",
        "bar_style": style,
        "size": 20.0,
        "min_val": 0,
        "max_val": 100,
        "show_value": True,
        "show_label": True,
        "show_range_labels": True,
        "show_min": True,
        "show_max": True,
    }
    layout["indicators"]["test_ind"] = cfg

    # Render on 1920x1080 canvas
    img, rx, ry, _ = _render_bar_indicator(
        1920, 1080, layout, "", "test_ind", 50.0, "%", "Test",
        cfg, 1080, 2, 24, None, 0, 100, 8, 3, int(0.20 * 1920), 1
    )
    canvas = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    rotated_paste(canvas, img, rx, ry, rot)
    real_bbox = canvas.getbbox()
    assert real_bbox is not None

    # Get computed bbox
    bx, by, bw, bh = get_layout_hud_bbox(layout, 1920, 1080)
    calc_x1, calc_y1, calc_x2, calc_y2 = bx, by, bx + bw, by + bh

    # Assert zero clipping
    assert real_bbox[0] >= calc_x1, f"Left clipped: real={real_bbox[0]} < calc={calc_x1}"
    assert real_bbox[1] >= calc_y1, f"Top clipped: real={real_bbox[1]} < calc={calc_y1}"
    assert real_bbox[2] <= calc_x2, f"Right clipped: real={real_bbox[2]} > calc={calc_x2}"
    assert real_bbox[3] <= calc_y2, f"Bottom clipped: real={real_bbox[3]} > calc={calc_y2}"


def test_compositor_preview_integration():
    """Verify that compose_overlay renders without errors with both ruler and segments."""
    layout = normalize_layout(None, 1920, 1080)
    layout["indicators"] = {
        "dist_visual": {
            "enabled": True, "label": "Distance", "x": 50.0, "y": 85.0,
            "rotation": 0, "form": "bar", "bar_style": "ruler", "size": 20.0,
            "min_val": 0, "max_val": 50,
        },
        "battery_visual": {
            "enabled": True, "label": "Battery", "x": 50.0, "y": 15.0,
            "rotation": 0, "form": "bar", "bar_style": "segments", "size": 20.0,
            "min_val": 0, "max_val": 100,
        },
    }

    img = compose_overlay(
        1920, 1080, layout, "",
        "", "",
        25.0, 500.0, 5000.0,
        150.0, 50.0, 300.0,
        100.0, 500.0, 25.0,
        indicator_values={"dist_visual": 12.5, "battery_visual": 82.0},
    )
    assert img is not None
    assert img.size == (1920, 1080)
    arr = np.asarray(img)
    # Check that pixels were actually drawn (non-empty overlay)
    assert np.count_nonzero(arr[..., 3]) > 0
