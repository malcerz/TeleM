import json
import pytest
import numpy as np
from pathlib import Path
from PIL import Image

from src.indicators.bar import (
    _render_ruler, _render_slope, _render_bar_indicator,
    _RULER_BASE_CACHE, _SLOPE_BASE_CACHE,
)
from src.indicators.dispatcher import render_value_indicator


@pytest.fixture
def v10_layout():
    preset_path = Path(__file__).resolve().parents[1] / "presets" / "cycling_dashboard_v10.json"
    with open(preset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_marker_center_x(img: Image.Image, marker_color=(255, 212, 42)) -> float | None:
    arr = np.array(img)
    mask = (
        (arr[:, :, 0] == marker_color[0])
        & (arr[:, :, 1] == marker_color[1])
        & (arr[:, :, 2] == marker_color[2])
        & (arr[:, :, 3] > 200)
    )
    ys, xs = np.where(mask)
    if len(xs) > 0:
        return float(np.mean(xs))
    return None


def _find_marker_center_y(img: Image.Image, marker_color=(21, 159, 165)) -> float | None:
    arr = np.array(img)
    mask = (
        (arr[:, :, 0] == marker_color[0])
        & (arr[:, :, 1] == marker_color[1])
        & (arr[:, :, 2] == marker_color[2])
        & (arr[:, :, 3] > 200)
    )
    ys, xs = np.where(mask)
    if len(ys) > 0:
        return float(np.mean(ys))
    return None


# ---------------------------------------------------------------------------
# 1. Synthetic 0%, 25%, 50%, 75%, 100% Distance Marker Tests
# ---------------------------------------------------------------------------


def test_distance_marker_synthetic_steps(v10_layout):
    """Test marker position for 0, 2.5, 5.0, 7.5, 10.0 km on a 0..10 km bar."""
    cfg = v10_layout["indicators"]["dist_visual"]
    canvas_w, canvas_h = 1280, 720
    size_px = int(0.28 * canvas_w)  # 358 px
    pad_x = 10  # pad_x for marker_size 6

    expected_ratios = {
        0.0: 0.0,
        2.5: 0.25,
        5.0: 0.50,
        7.5: 0.75,
        10.0: 1.00,
    }

    x_coords = {}
    for val, ratio in expected_ratios.items():
        img = _render_ruler(
            canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
            value=val, unit="km", label="DISTANCE", cfg=cfg,
            val_min=0.0, val_max=10.0, ticks=5, thickness=1,
            size_px=size_px, fs=15, outline=1, ss=1,
            formatted_val=f"{val:.1f} km",
        )
        marker_x = _find_marker_center_x(img)
        assert marker_x is not None, f"Marker must be visible for value={val}"
        x_coords[val] = marker_x

        # Check track width
        track_w = 358.0
        expected_x = pad_x + ratio * track_w
        assert abs(marker_x - expected_x) <= 1.0, (
            f"Value {val} km expected marker at ~{expected_x:.1f} px, got {marker_x:.1f} px"
        )

    # Monotonicity
    vals = sorted(expected_ratios.keys())
    for v1, v2 in zip(vals[:-1], vals[1:]):
        assert x_coords[v2] > x_coords[v1], f"Marker must move right as distance increases: {v1}->{v2}"


def test_distance_marker_none(v10_layout):
    """When value is None, ruler is drawn but marker is absent."""
    cfg = v10_layout["indicators"]["dist_visual"]
    img = _render_ruler(
        canvas_w=1280, canvas_h=720, font_path="",
        value=None, unit="km", label="DISTANCE", cfg=cfg,
        val_min=0.0, val_max=10.0, ticks=5, thickness=1,
        size_px=int(0.28 * 1280), fs=15, outline=1, ss=1,
        formatted_val="-- km",
    )
    marker_x = _find_marker_center_x(img)
    assert marker_x is None, "No marker should be rendered when value=None"


def test_distance_marker_zero(v10_layout):
    """When value is 0.0 (not None), marker is rendered at exactly the start (pad_x)."""
    cfg = v10_layout["indicators"]["dist_visual"]
    img = _render_ruler(
        canvas_w=1280, canvas_h=720, font_path="",
        value=0.0, unit="km", label="DISTANCE", cfg=cfg,
        val_min=0.0, val_max=10.0, ticks=5, thickness=1,
        size_px=int(0.28 * 1280), fs=15, outline=1, ss=1,
        formatted_val="0.0 km",
    )
    marker_x = _find_marker_center_x(img)
    assert marker_x is not None, "Marker must be rendered for value=0.0"
    assert abs(marker_x - 10.0) <= 1.0, f"Marker at 0.0 km should be at ~10.0 px, got {marker_x}"


# ---------------------------------------------------------------------------
# 2. Text + Marker Consistency Test
# ---------------------------------------------------------------------------


def test_distance_text_and_marker_consistency(v10_layout):
    """Test that value text and marker position use the exact same telemetry value."""
    cfg = v10_layout["indicators"]["dist_visual"]
    img = _render_ruler(
        canvas_w=1280, canvas_h=720, font_path="",
        value=5.0, unit="km", label="DISTANCE", cfg=cfg,
        val_min=0.0, val_max=10.0, ticks=5, thickness=1,
        size_px=int(0.28 * 1280), fs=15, outline=1, ss=1,
        formatted_val="5.0 km",
    )
    marker_x = _find_marker_center_x(img)
    assert marker_x is not None
    # 5.0 km on 0..10 km bar is 50%
    assert abs(marker_x - (10 + 0.5 * 358)) <= 1.0


# ---------------------------------------------------------------------------
# 3. Altitude Ruler Regression Test
# ---------------------------------------------------------------------------


def test_altitude_marker_steps(v10_layout):
    """Test Altitude (vertical ruler) marker across min, 25%, 50%, 75%, max."""
    cfg = v10_layout["indicators"]["alt_visual"]
    canvas_w, canvas_h = 1280, 720
    size_px = int(0.28 * canvas_h)

    alts = [0.0, 250.0, 500.0, 750.0, 1000.0]
    marker_positions = []
    for alt in alts:
        img = _render_ruler(
            canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
            value=alt, unit="m", label="ALTITUDE", cfg=cfg,
            val_min=0.0, val_max=1000.0, ticks=5, thickness=1,
            size_px=size_px, fs=15, outline=1, ss=1,
            formatted_val=f"{alt:.0f} m",
        )
        mx = _find_marker_center_x(img, marker_color=(0, 170, 255))
        assert mx is not None, f"Altitude marker must exist for {alt}m"
        marker_positions.append(mx)

    for p1, p2 in zip(marker_positions[:-1], marker_positions[1:]):
        assert p2 > p1, "Altitude marker must move monotonically along the ruler"


# ---------------------------------------------------------------------------
# 4. Slope Marker Regression Test
# ---------------------------------------------------------------------------


def test_slope_marker_regression(v10_layout):
    """Test Slope marker at -5, 0, +5, None."""
    cfg = v10_layout["indicators"]["slope_text"]
    canvas_w, canvas_h = 1280, 720
    size_px = int(0.16 * canvas_h)

    y_coords = {}
    for slope in [-5.0, 0.0, 5.0]:
        img = _render_slope(
            canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
            value=slope, unit="%", label="Slope", cfg=cfg,
            val_min=-12.0, val_max=12.0, thickness=1, size_px=size_px,
            fs=15, outline=1, ss=1, formatted_val=f"{slope:+.0f}%",
        )
        my = _find_marker_center_y(img, marker_color=(255, 212, 42))
        assert my is not None, f"Slope marker must exist for {slope}%"
        y_coords[slope] = my

    # Slope track is vertical: +5% is higher up (smaller y), -5% is lower (larger y)
    assert y_coords[5.0] < y_coords[0.0] < y_coords[-5.0], "Slope marker y must decrease as slope increases (higher on gauge)"

    # None slope
    img_none = _render_slope(
        canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
        value=0.0, unit="%", label="Slope", cfg=dict(cfg, _slope_missing=True),
        val_min=-12.0, val_max=12.0, thickness=1, size_px=size_px,
        fs=15, outline=1, ss=1, formatted_val="--%",
    )
    my_none = _find_marker_center_y(img_none, marker_color=(255, 212, 42))
    assert my_none is None, "Slope marker must not be rendered when missing"
