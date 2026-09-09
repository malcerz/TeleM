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
from src.indicators.compositor import compose_overlay


@pytest.fixture
def v10_layout():
    preset_path = Path(__file__).resolve().parents[1] / "presets" / "cycling_dashboard_v10.json"
    with open(preset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_marker_pixel_x(img: Image.Image, marker_color=(255, 212, 42)) -> float | None:
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


def _find_horizontal_scale_span(img: Image.Image, cfg: dict) -> tuple[int, int]:
    arr = np.array(img)
    colors = [
        tuple(bytes.fromhex(str(cfg[key]).lstrip("#")))
        for key in ("track_color", "tick_color")
    ]
    mask = np.zeros(arr.shape[:2], dtype=bool)
    for color in colors:
        mask |= np.all(arr[:, :, :3] == color, axis=2) & (arr[:, :, 3] > 200)
    row = int(np.argmax(mask.sum(axis=1)))
    xs = np.where(mask[row])[0]
    assert len(xs), "horizontal scale not found"
    return int(xs.min()), int(xs.max())


def _render_distance_ruler(cfg: dict, value, val_min=0.0, val_max=10.0):
    return _render_ruler(
        canvas_w=1280, canvas_h=720, font_path="", value=value,
        unit="km", label="DISTANCE", cfg=cfg, val_min=val_min,
        val_max=val_max, ticks=5, thickness=1, size_px=int(0.28 * 1280),
        fs=15, outline=1, ss=1,
        formatted_val=f"{value:.1f} km" if value is not None else None,
    )


# ---------------------------------------------------------------------------
# 1. Raster Marker Detection Test: 0, 2.5, 5.0, 7.5, 10.0 km
# ---------------------------------------------------------------------------


def test_raster_marker_detection_steps(v10_layout):
    """Test actual pixels of rendered raster for 0%, 25%, 50%, 75%, 100%."""
    cfg = v10_layout["indicators"]["dist_visual"]
    canvas_w, canvas_h = 1280, 720
    size_px = int(0.28 * canvas_w)  # 358 px

    steps = [
        (0.0, 0.0),
        (2.5, 0.25),
        (5.0, 0.50),
        (7.5, 0.75),
        (10.0, 1.00),
    ]

    positions = {}
    for val, _expected_ratio in steps:
        img = _render_distance_ruler(cfg, val)
        pixel_x = _find_marker_pixel_x(img)
        assert pixel_x is not None, f"Marker pixel must exist for value={val}"
        positions[val] = pixel_x

    scale_start, scale_end = _find_horizontal_scale_span(
        _render_distance_ruler(cfg, None), cfg
    )
    assert abs(positions[0.0] - scale_start) <= 1.0
    assert abs(positions[10.0] - scale_end) <= 1.0
    for val, expected_ratio in steps:
        expected_x = positions[0.0] + expected_ratio * (
            positions[10.0] - positions[0.0]
        )
        assert abs(positions[val] - expected_x) <= 1.0


# ---------------------------------------------------------------------------
# 2. Real ~11.9 km Case: Marker at ~50% of 0..24 km Ruler
# ---------------------------------------------------------------------------


def test_real_11_9_km_marker_position(v10_layout):
    """When distance is 11.887 km on a 0..23.926 km ruler, marker pixel is at ~49.7%."""
    cfg = v10_layout["indicators"]["dist_visual"]
    canvas_w, canvas_h = 1280, 720
    size_px = int(0.28 * canvas_w)  # 358 px

    val = 11.8866
    val_min = 0.0
    val_max = 23.9264
    expected_ratio = (val - val_min) / (val_max - val_min)  # ~0.4968

    img = _render_ruler(
        canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
        value=val, unit="km", label="DISTANCE", cfg=cfg,
        val_min=val_min, val_max=val_max, ticks=5, thickness=1,
        size_px=size_px, fs=15, outline=1, ss=1,
        formatted_val="11.9 km",
    )
    pixel_x = _find_marker_pixel_x(img)
    assert pixel_x is not None
    start_x = _find_marker_pixel_x(
        _render_distance_ruler(cfg, val_min, val_min, val_max)
    )
    end_x = _find_marker_pixel_x(
        _render_distance_ruler(cfg, val_max, val_min, val_max)
    )
    assert start_x is not None and end_x is not None
    expected_x = start_x + expected_ratio * (end_x - start_x)
    assert abs(pixel_x - expected_x) <= 1.0, (
        f"11.9 km on 0..23.9 km ruler expected marker at ~{expected_x:.1f} px, got {pixel_x:.1f} px"
    )


# ---------------------------------------------------------------------------
# 3. Cache Sequence Test (0 -> 5 -> 10 -> 2.5 -> 7.5 -> 0)
# ---------------------------------------------------------------------------


def test_cache_sequence_responsiveness(v10_layout):
    """Test that static cache does not freeze or leak previous marker positions."""
    cfg = v10_layout["indicators"]["dist_visual"]
    canvas_w, canvas_h = 1280, 720
    size_px = int(0.28 * canvas_w)  # 358 px
    start_x = _find_marker_pixel_x(_render_distance_ruler(cfg, 0.0))
    end_x = _find_marker_pixel_x(_render_distance_ruler(cfg, 10.0))
    assert start_x is not None and end_x is not None

    sequence = [0.0, 5.0, 10.0, 2.5, 7.5, 0.0]
    for val in sequence:
        img = _render_ruler(
            canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
            value=val, unit="km", label="DISTANCE", cfg=cfg,
            val_min=0.0, val_max=10.0, ticks=5, thickness=1,
            size_px=size_px, fs=15, outline=1, ss=1,
            formatted_val=f"{val:.1f} km",
        )
        pixel_x = _find_marker_pixel_x(img)
        assert pixel_x is not None
        expected_x = start_x + (val / 10.0) * (end_x - start_x)
        assert abs(pixel_x - expected_x) <= 1.0, (
            f"Value {val} in sequence got pixel_x={pixel_x:.1f}, expected {expected_x:.1f}"
        )


# ---------------------------------------------------------------------------
# 4. None / Zero Boundary Cases
# ---------------------------------------------------------------------------


def test_none_and_zero_raster(v10_layout):
    """Test None -> no marker, Zero -> marker at pad_x."""
    cfg = v10_layout["indicators"]["dist_visual"]
    canvas_w, canvas_h = 1280, 720
    size_px = int(0.28 * canvas_w)

    # None
    img_none = _render_ruler(
        canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
        value=None, unit="km", label="DISTANCE", cfg=cfg,
        val_min=0.0, val_max=10.0, ticks=5, thickness=1,
        size_px=size_px, fs=15, outline=1, ss=1,
        formatted_val="-- km",
    )
    assert _find_marker_pixel_x(img_none) is None

    # Zero
    img_zero = _render_ruler(
        canvas_w=canvas_w, canvas_h=canvas_h, font_path="",
        value=0.0, unit="km", label="DISTANCE", cfg=cfg,
        val_min=0.0, val_max=10.0, ticks=5, thickness=1,
        size_px=size_px, fs=15, outline=1, ss=1,
        formatted_val="0.0 km",
    )
    scale_start, _ = _find_horizontal_scale_span(
        _render_distance_ruler(cfg, None), cfg
    )
    assert abs(_find_marker_pixel_x(img_zero) - scale_start) <= 1.0


# ---------------------------------------------------------------------------
# 5. Compositor Dynamic Distance Scaling (dist_visual, dist_text, fit_distance_text)
# ---------------------------------------------------------------------------


def _compose_dist_bar(key, v10_layout, **extra_cfg):
    """Compose a single distance bar and return the marker center-x in the bbox crop."""
    layout = json.loads(json.dumps(v10_layout))
    cfg = {
        "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
        "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0, "thickness": 1,
        "min_val": 0.0, "max_val": 100.0, "ticks": 5, "show_value": True, "source": "fit", "unit": "km",
        "marker_color": "#FFD42A",
    }
    cfg.update(extra_cfg)
    layout["indicators"] = {key: cfg}
    bboxes = {}
    overlay = compose_overlay(
        1280, 720, layout, "",
        date_text="2026-08-14",
        time_text="11:18:03",
        speed_value=0.0,
        distance_m=11886.6,
        max_distance_m=23926.4,
        _bboxes=bboxes,
    )
    bb = bboxes.get(key)
    assert bb is not None
    ox, oy, ow, oh = bb
    crop = overlay.crop((ox, oy, ox + ow, oy + oh))
    arr = np.array(crop)
    mask = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 212) & (arr[:, :, 2] == 42) & (arr[:, :, 3] > 200)
    ys, xs = np.where(mask)
    assert len(xs) > 0, f"{key}: marker pixel not found"
    return float(np.mean(xs))


def test_compositor_distance_manual_scale_respected(v10_layout):
    """MANUAL (auto_scale=False / brak): compose_overlay MUSI szanować ręczne
    max_val=100.0 — marker dla 11.886 km stoi na ~11.9% (a nie ~50%)."""
    for key in ("dist_visual", "dist_text"):
        cx = _compose_dist_bar(key, v10_layout)
        # 11.886 km / 100 km ≈ 11.9% -> lewa część cropu (max_val=100 NIE nadpisany)
        assert cx < 100.0, f"{key}: manual max_val=100 nie został uszanowany (marker x={cx:.1f})"


def test_compositor_distance_auto_scale(v10_layout):
    """AUTO (auto_scale=True): compose_overlay nadpisuje max_val pełnym
    dystansem (23.926 km) — marker dla 11.886 km stoi na ~50%."""
    for key in ("dist_visual", "dist_text"):
        cx = _compose_dist_bar(key, v10_layout, auto_scale=True)
        # 11.886 / 23.926 ≈ 49.7% -> środek cropu (~188 px)
        assert 170 <= cx <= 200, f"{key} auto_scale marker expected ~188 px, got {cx:.1f} px"
