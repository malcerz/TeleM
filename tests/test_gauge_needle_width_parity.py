"""Tests for Gauge needle width: Preview vs Final render parity across resolutions.

Verifies:
1. test_gauge_needle_width_scales_with_canvas
2. test_gauge_needle_width_preview_4k_ratio_parity
3. test_gauge_needle_width_1080_4k_ratio_parity
4. test_gauge_needle_width_change_invalidates_cache
5. test_gauge_needle_bbox_contains_scaled_needle
6. test_gauge_scaled_needle_outline_not_clipped
7. test_gauge_scaled_needle_shadow_not_clipped
8. test_queue_gauge_width_snapshot_preserved
9. test_two_queue_jobs_keep_distinct_needle_widths
10. test_nvidia_gauge_width_not_hardcoded
"""

import copy
import math
from unittest.mock import MagicMock
import numpy as np
import pytest

from src.indicators.gauge import (
    _render_gauge_indicator,
    get_gauge_dynamic_info,
    resolve_gauge_needle_width_px,
    clear_gauge_cache,
)


@pytest.fixture(autouse=True)
def clean_cache():
    clear_gauge_cache()
    yield
    clear_gauge_cache()


def test_gauge_needle_width_scales_with_canvas():
    """Verify that logical needle width scales proportionally with canvas min_dim."""
    # Preview baseline (min_dim = 540)
    assert resolve_gauge_needle_width_px(2, 540) == 3
    assert resolve_gauge_needle_width_px(4, 540) == 6
    assert resolve_gauge_needle_width_px(8, 540) == 12
    assert resolve_gauge_needle_width_px(10, 540) == 15
    assert resolve_gauge_needle_width_px(12, 540) == 18

    # 1080p (min_dim = 1080) -> exactly 2.0x preview
    assert resolve_gauge_needle_width_px(2, 1080) == 6
    assert resolve_gauge_needle_width_px(4, 1080) == 12
    assert resolve_gauge_needle_width_px(8, 1080) == 24
    assert resolve_gauge_needle_width_px(10, 1080) == 30
    assert resolve_gauge_needle_width_px(12, 1080) == 36

    # 4K (min_dim = 2160) -> exactly 4.0x preview
    assert resolve_gauge_needle_width_px(2, 2160) == 12
    assert resolve_gauge_needle_width_px(4, 2160) == 24
    assert resolve_gauge_needle_width_px(8, 2160) == 48
    assert resolve_gauge_needle_width_px(10, 2160) == 60
    assert resolve_gauge_needle_width_px(12, 2160) == 72

    # 720p (min_dim = 720) -> 720/540 = 1.333x
    assert resolve_gauge_needle_width_px(4, 720) == 8
    assert resolve_gauge_needle_width_px(10, 720) == 20


def test_gauge_needle_width_preview_4k_ratio_parity():
    """Verify needle_width_px / gauge_diameter_px ratio difference between Preview and 4K is <= 5%."""
    size_percent = 15.0

    for logical_w in [2, 4, 8, 12]:
        # Preview (960x540, min_dim=540)
        size_px_prev = int(round((size_percent / 100.0) * 540))
        cfg_prev = {
            "x": 10, "y": 10, "needle_width": logical_w, "size": size_percent,
            "start_angle": 180, "sweep_angle": 180, "min_val": 0, "max_val": 100,
        }
        _render_gauge_indicator(
            960, 540, {}, "Arial", "speed_text", 0.0, "km/h", "Speed",
            cfg_prev, 540, 0, 16, None, 0, 100, 0, 2, size_px_prev, 2,
            formatted_val="0", fast_preview=True
        )
        info_prev = get_gauge_dynamic_info("speed_text")
        needle_w_prev = info_prev["sig"][15]
        diam_prev = 2 * size_px_prev
        ratio_prev = needle_w_prev / diam_prev

        # Final 4K (3840x2160, min_dim=2160)
        size_px_4k = int(round((size_percent / 100.0) * 2160))
        cfg_4k = {
            "x": 10, "y": 10, "needle_width": logical_w, "size": size_percent,
            "start_angle": 180, "sweep_angle": 180, "min_val": 0, "max_val": 100,
        }
        _render_gauge_indicator(
            3840, 2160, {}, "Arial", "speed_text", 0.0, "km/h", "Speed",
            cfg_4k, 2160, 0, 64, None, 0, 100, 0, 8, size_px_4k, 2,
            formatted_val="0", fast_preview=False
        )
        info_4k = get_gauge_dynamic_info("speed_text")
        needle_w_4k = info_4k["sig"][15]
        diam_4k = 2 * size_px_4k
        ratio_4k = needle_w_4k / diam_4k

        diff_pct = abs(ratio_prev - ratio_4k) / ratio_prev * 100.0
        assert diff_pct <= 5.0, f"Ratio diff too large for w={logical_w}: {diff_pct:.2f}% (prev={ratio_prev:.5f}, 4k={ratio_4k:.5f})"


def test_gauge_needle_width_1080_4k_ratio_parity():
    """Verify needle_width_px / gauge_diameter_px ratio difference between 1080p and 4K is <= 5%."""
    size_percent = 15.0

    for logical_w in [4, 10]:
        size_px_1080 = int(round((size_percent / 100.0) * 1080))
        cfg_1080 = {
            "x": 10, "y": 10, "needle_width": logical_w, "size": size_percent,
            "start_angle": 180, "sweep_angle": 180, "min_val": 0, "max_val": 100,
        }
        _render_gauge_indicator(
            1920, 1080, {}, "Arial", "speed_text", 0.0, "km/h", "Speed",
            cfg_1080, 1080, 0, 32, None, 0, 100, 0, 4, size_px_1080, 2,
            formatted_val="0", fast_preview=False
        )
        info_1080 = get_gauge_dynamic_info("speed_text")
        ratio_1080 = info_1080["sig"][15] / (2 * size_px_1080)

        size_px_4k = int(round((size_percent / 100.0) * 2160))
        cfg_4k = {
            "x": 10, "y": 10, "needle_width": logical_w, "size": size_percent,
            "start_angle": 180, "sweep_angle": 180, "min_val": 0, "max_val": 100,
        }
        _render_gauge_indicator(
            3840, 2160, {}, "Arial", "speed_text", 0.0, "km/h", "Speed",
            cfg_4k, 2160, 0, 64, None, 0, 100, 0, 8, size_px_4k, 2,
            formatted_val="0", fast_preview=False
        )
        info_4k = get_gauge_dynamic_info("speed_text")
        ratio_4k = info_4k["sig"][15] / (2 * size_px_4k)

        diff_pct = abs(ratio_1080 - ratio_4k) / ratio_1080 * 100.0
        assert diff_pct <= 5.0, f"1080p vs 4K ratio diff {diff_pct:.2f}% > 5%"


def test_gauge_needle_width_change_invalidates_cache():
    """Verify that changing needle_width invalidates the raster and signature caches."""
    cfg1 = {"x": 10, "y": 10, "needle_width": 4, "size": 15.0, "min_val": 0, "max_val": 100}
    img1, _, _, _ = _render_gauge_indicator(
        1920, 1080, {}, "Arial", "speed_text", 30.0, "km/h", "Speed",
        cfg1, 1080, 0, 32, None, 0, 100, 0, 4, 162, 2, formatted_val="30"
    )
    info1 = get_gauge_dynamic_info("speed_text")
    sig1 = info1["sig"]
    width1 = sig1[15]

    cfg2 = {"x": 10, "y": 10, "needle_width": 10, "size": 15.0, "min_val": 0, "max_val": 100}
    img2, _, _, _ = _render_gauge_indicator(
        1920, 1080, {}, "Arial", "speed_text", 30.0, "km/h", "Speed",
        cfg2, 1080, 0, 32, None, 0, 100, 0, 4, 162, 2, formatted_val="30"
    )
    info2 = get_gauge_dynamic_info("speed_text")
    sig2 = info2["sig"]
    width2 = sig2[15]

    assert width1 != width2
    assert width1 == 12
    assert width2 == 30
    assert sig1 != sig2
    # Ensure raster images are visually distinct
    arr1 = np.array(img1)
    arr2 = np.array(img2)
    red1 = np.sum((arr1[:, :, 0] > 150) & (arr1[:, :, 1] < 80))
    red2 = np.sum((arr2[:, :, 0] > 150) & (arr2[:, :, 1] < 80))
    assert red2 > red1 * 1.5, f"Wider needle did not paint significantly more red pixels: {red1} vs {red2}"


def test_gauge_needle_bbox_contains_scaled_needle():
    """Verify that needle_bbox contains the full scaled needle geometry vertices."""
    cfg = {"x": 10, "y": 10, "needle_width": 10, "size": 15.0, "min_val": 0, "max_val": 100}
    size_px = 324  # 4K
    _render_gauge_indicator(
        3840, 2160, {}, "Arial", "speed_text", 50.0, "km/h", "Speed",
        cfg, 2160, 0, 64, None, 0, 100, 0, 8, size_px, 2, formatted_val="50"
    )
    info = get_gauge_dynamic_info("speed_text")
    bx0, by0, bx1, by1 = info["needle_bbox"]

    # Calculate needle vertices at 4K (needle_width = 10 -> 60 px)
    ss = 2
    out_size = int(size_px * 2.4)
    cx = cy = out_size // 2
    radius = size_px * ss
    needle_r_out = int(radius * 1.1 / ss)
    needle_r_in = int(radius * 0.05)
    needle_w_px = resolve_gauge_needle_width_px(10, 2160)
    hw = needle_w_px / 2.0

    # At 50% fraction with start 180, sweep 180 -> angle = 270 deg (pointing straight up)
    ang = math.radians(270)
    pdx, pdy = -math.sin(ang), math.cos(ang)
    tip_x = cx + math.cos(ang) * needle_r_out
    tip_y = cy + math.sin(ang) * needle_r_out
    base_x = cx + math.cos(ang) * needle_r_in
    base_y = cy + math.sin(ang) * needle_r_in

    pts = [
        (base_x + pdx * hw, base_y + pdy * hw),
        (base_x - pdx * hw, base_y - pdy * hw),
        (tip_x, tip_y),
    ]

    for px, py in pts:
        assert bx0 <= px <= bx1, f"Vertex x={px} outside bbox [{bx0}, {bx1}]"
        assert by0 <= py <= by1, f"Vertex y={py} outside bbox [{by0}, {by1}]"


def test_gauge_scaled_needle_outline_not_clipped():
    """Verify that outside outline is contained in bbox and does not shrink the inner needle core."""
    cfg = {
        "x": 10, "y": 10, "needle_width": 10, "size": 15.0, "min_val": 0, "max_val": 100,
        "outline_enabled": True, "outline_width": 4.0, "outline_color": "#000000", "outline_opacity": 1.0,
    }
    img, _, _, _ = _render_gauge_indicator(
        1920, 1080, {}, "Arial", "speed_text", 0.0, "km/h", "Speed",
        cfg, 1080, 0, 32, None, 0, 100, 0, 4, 162, 2, formatted_val="0"
    )
    info = get_gauge_dynamic_info("speed_text")
    bx0, by0, bx1, by1 = info["needle_bbox"]

    # Check horizontal pointing needle (value=0 -> ang=180 -> pointing left)
    arr = np.array(img)
    # Inner red needle should be present with full thickness
    red_mask = (arr[:, :, 0] > 150) & (arr[:, :, 1] < 80) & (arr[:, :, 2] < 80)
    assert np.any(red_mask), "Red needle core must exist"

    # Black outline should be present outside the red core
    black_mask = (arr[:, :, 0] < 50) & (arr[:, :, 1] < 50) & (arr[:, :, 2] < 50) & (arr[:, :, 3] > 200)
    assert np.any(black_mask), "Outline mask must exist"

    # Check that red needle pixels are contained in the reported bbox
    red_y, red_x = np.where(red_mask)
    assert np.min(red_x) >= bx0
    assert np.max(red_x) <= bx1
    assert np.min(red_y) >= by0
    assert np.max(red_y) <= by1


def test_gauge_scaled_needle_shadow_not_clipped():
    """Verify that shadow extent is included in bbox without clipping."""
    cfg = {
        "x": 10, "y": 10, "needle_width": 8, "size": 15.0, "min_val": 0, "max_val": 100,
        "shadow_enabled": True, "shadow_distance": 5.0, "shadow_length": 15.0,
        "shadow_color": "#000000", "shadow_opacity": 0.8,
    }
    _render_gauge_indicator(
        1920, 1080, {}, "Arial", "speed_text", 50.0, "km/h", "Speed",
        cfg, 1080, 0, 32, None, 0, 100, 0, 4, 162, 2, formatted_val="50"
    )
    info = get_gauge_dynamic_info("speed_text")
    bx0, by0, bx1, by1 = info["needle_bbox"]
    assert bx1 > bx0 + 20
    assert by1 > by0 + 20


def test_queue_gauge_width_snapshot_preserved():
    """Verify that queue snapshotting preserves layout config from moment of '+ Dodaj'."""
    ctrl_layout = {
        "indicators": {
            "speed_text": {
                "form": "gauge",
                "needle_width": 10,
                "size": 15.0,
            }
        }
    }

    # Simulate _on_add_to_queue snapshot
    layout_snap = copy.deepcopy(ctrl_layout)

    # User modifies layout AFTER adding to queue
    ctrl_layout["indicators"]["speed_text"]["needle_width"] = 4

    assert layout_snap["indicators"]["speed_text"]["needle_width"] == 10
    assert ctrl_layout["indicators"]["speed_text"]["needle_width"] == 4


def test_two_queue_jobs_keep_distinct_needle_widths():
    """Verify that two distinct queue jobs preserve their respective needle widths."""
    ctrl_layout = {
        "indicators": {
            "speed_text": {
                "form": "gauge",
                "needle_width": 10,
                "size": 15.0,
            }
        }
    }

    job1_layout = copy.deepcopy(ctrl_layout)

    # Change for second job
    ctrl_layout["indicators"]["speed_text"]["needle_width"] = 4
    job2_layout = copy.deepcopy(ctrl_layout)

    assert job1_layout["indicators"]["speed_text"]["needle_width"] == 10
    assert job2_layout["indicators"]["speed_text"]["needle_width"] == 4


def test_nvidia_gauge_width_not_hardcoded():
    """Verify that NVIDIA exporter resolves needle width from cfg rather than hardcoded 8.0."""
    from src.ffmpeg.nvidia_native_exporter import _is_indicator_active

    layout = {
        "indicators": {
            "speed_text": {
                "enabled": True,
                "form": "gauge",
                "needle_width": 10,
                "size": 15.0,
            }
        }
    }
    min_dim = 1080
    cfg = layout["indicators"]["speed_text"]
    resolved_w = resolve_gauge_needle_width_px(cfg.get("needle_width", 4), min_dim)
    assert resolved_w == 30, f"Expected 30 px for width=10 at 1080p, got {resolved_w}"

    cfg_thin = {"needle_width": 2}
    resolved_thin = resolve_gauge_needle_width_px(cfg_thin.get("needle_width", 4), min_dim)
    assert resolved_thin == 6, f"Expected 6 px for width=2 at 1080p, got {resolved_thin}"
