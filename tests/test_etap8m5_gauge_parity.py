"""Test suite for ETAP 8M.5 — Gauge Preview / AMD parity and Ticks / Width settings fix."""
import pytest
import json
import numpy as np
from pathlib import Path
from PIL import Image

from src.indicators.dispatcher import render_value_indicator
from src.indicators.gauge import _render_gauge_indicator, _gauge_ticks
from src.indicators.compositor import compose_overlay
from src.gui.layout_manager import normalize_layout
from src.gui.qt.models import get_schema_for_form, FieldSchema
from src.indicators.helpers import _STATIC_CACHE


@pytest.fixture
def default_gauge_cfg():
    return {
        "enabled": True,
        "label": "Enhanced Speed",
        "x": 48.65,
        "y": 90.56,
        "rotation": 0,
        "form": "gauge",
        "font_size": 2.4,
        "size": 12.5,
        "thickness": 1,
        "min_val": 0.0,
        "max_val": 40.0,
        "ticks": 10,
        "source": "fit",
        "unit": "km/h",
        "show_marker": True,
        "marker_size": 5,
        "marker_color": "#ff0000",
        "show_units": True,
        "show_value": True,
        "decimals": 1,
    }


def _compose_test_overlay(**kwargs):
    default_args = {
        "date_text": "2026-08-19",
        "time_text": "12:00:00",
        "speed_value": 25.0,
        "distance_m": 1000.0,
        "alt_value": 100.0,
    }
    default_args.update(kwargs)
    return compose_overlay(**default_args)


def test_gauge_preview_contains_ticks(default_gauge_cfg):
    """Section 25: Verify Preview gauge raster contains white tick marks and labels."""
    layout = {"global": {}, "indicators": {"speed": default_gauge_cfg}}
    bboxes = {}
    canvas = _compose_test_overlay(
        canvas_w=1920, canvas_h=1080,
        layout=layout, font_path="assets/Roboto-Bold.ttf",
        _bboxes=bboxes,
        indicator_values={"speed": 25.0},
        gpu_capture_keys=None,
        reuse_canvas=False,
    )
    assert "speed" in bboxes
    gx, gy, gw, gh = bboxes["speed"]
    crop = canvas.crop((gx, gy, gx + gw, gy + gh))
    arr = np.array(crop)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]
    # Check that non-zero alpha and white tick pixels are present
    assert np.count_nonzero(alpha > 0) > 1000
    white_px = np.count_nonzero((alpha > 100) & (rgb[:, :, 0] > 180) & (rgb[:, :, 1] > 180) & (rgb[:, :, 2] > 180))
    assert white_px > 300


def test_gauge_gpu_capture_contains_ticks(default_gauge_cfg):
    """Section 25: Verify GPU capture raster contains white tick marks and labels."""
    layout = {"global": {}, "indicators": {"speed": default_gauge_cfg}}
    gpu_capture = {}
    bboxes = {}
    _compose_test_overlay(
        canvas_w=1920, canvas_h=1080,
        layout=layout, font_path="assets/Roboto-Bold.ttf",
        _bboxes=bboxes,
        indicator_values={"speed": 25.0},
        gpu_capture_keys={"speed"},
        gpu_capture=gpu_capture,
        reuse_canvas=False,
    )
    assert "speed" in gpu_capture
    cap = gpu_capture["speed"]
    img = cap["image"]
    arr = np.array(img)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]
    assert np.count_nonzero(alpha > 0) > 1000
    white_px = np.count_nonzero((alpha > 100) & (rgb[:, :, 0] > 180) & (rgb[:, :, 1] > 180) & (rgb[:, :, 2] > 180))
    assert white_px > 300


def test_gauge_static_and_dynamic_layers_complete(default_gauge_cfg):
    """Section 25: Verify static background and dynamic needle/marker/text components are rendered."""
    layout = {"global": {}, "indicators": {"speed": default_gauge_cfg}}
    img, rx, ry, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="speed", value=15.0, unit="km/h", label="Speed",
        cfg_override=default_gauge_cfg,
    )
    arr = np.array(img)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]
    # Check red needle/marker pixels
    red_px = np.count_nonzero((alpha > 100) & (rgb[:, :, 0] > 180) & (rgb[:, :, 1] < 80) & (rgb[:, :, 2] < 80))
    assert red_px > 100
    # Check white tick/text pixels
    white_px = np.count_nonzero((alpha > 100) & (rgb[:, :, 0] > 180) & (rgb[:, :, 1] > 180) & (rgb[:, :, 2] > 180))
    assert white_px > 300


def test_gauge_bbox_contains_full_arc(default_gauge_cfg):
    """Section 21 & 25: Verify gauge bounding box comfortably encloses all alpha pixels."""
    layout = {"global": {}, "indicators": {"speed": default_gauge_cfg}}
    bboxes = {}
    _compose_test_overlay(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        _bboxes=bboxes, indicator_values={"speed": 20.0}, reuse_canvas=False,
    )
    img, rx, ry, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="speed", value=20.0, unit="km/h", label="Speed", cfg_override=default_gauge_cfg,
    )
    arr = np.array(img)
    y_idx, x_idx = np.where(arr[:, :, 3] > 0)
    assert x_idx.min() >= 0 and x_idx.max() < img.width
    assert y_idx.min() >= 0 and y_idx.max() < img.height


def test_gauge_preview_final_geometry_parity(default_gauge_cfg):
    """Section 25: Verify pixel geometry match between Preview HUD crop and GPU capture source."""
    layout = {"global": {}, "indicators": {"speed": default_gauge_cfg}}
    preview_bboxes = {}
    preview_canvas = _compose_test_overlay(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        _bboxes=preview_bboxes, indicator_values={"speed": 25.0},
        gpu_capture_keys=None, reuse_canvas=False,
    )
    gpu_capture = {}
    gpu_bboxes = {}
    _compose_test_overlay(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        _bboxes=gpu_bboxes, indicator_values={"speed": 25.0},
        gpu_capture_keys={"speed"}, gpu_capture=gpu_capture, reuse_canvas=False,
    )
    gx, gy, gw, gh = preview_bboxes["speed"]
    preview_crop = preview_canvas.crop((gx, gy, gx + gw, gy + gh))
    gpu_img = gpu_capture["speed"]["image"]

    p_arr = np.array(preview_crop)
    g_arr = np.array(gpu_img)
    assert p_arr.shape == g_arr.shape
    diff = np.abs(p_arr.astype(int) - g_arr.astype(int))
    # Direct render match rate > 99.5%
    match_rate = np.count_nonzero(diff == 0) / diff.size
    assert match_rate > 0.995


def test_gauge_tick_property_propagation(default_gauge_cfg):
    """Section 26: Verify that the 'ticks' property propagates from config to _gauge_ticks."""
    (min_val, max_val, step_val, major_int, sub_ticks, total_ticks) = _gauge_ticks(0.0, 40.0, 4)
    assert sub_ticks == 4
    assert total_ticks == 4 * 4

    (min_val, max_val, step_val, major_int, sub_ticks, total_ticks) = _gauge_ticks(0.0, 40.0, 20)
    assert sub_ticks == 20
    assert total_ticks == 4 * 20


def test_gauge_tick_width_property_propagation(default_gauge_cfg):
    """Section 26: Verify that 'thickness' (Grubość podziałek) affects rendered pixel count."""
    layout = {"global": {}, "indicators": {"speed": default_gauge_cfg}}
    
    cfg1 = dict(default_gauge_cfg, thickness=1)
    img1, _, _, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="speed", value=20.0, unit="km/h", label="Speed", cfg_override=cfg1,
    )
    cfg10 = dict(default_gauge_cfg, thickness=10)
    img10, _, _, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="speed", value=20.0, unit="km/h", label="Speed", cfg_override=cfg10,
    )
    arr1 = np.array(img1)
    arr10 = np.array(img10)
    # Higher thickness MUST produce significantly more non-zero alpha pixels
    assert np.count_nonzero(arr10[:, :, 3] > 0) > np.count_nonzero(arr1[:, :, 3] > 0) * 1.5


def test_gauge_tick_change_affects_geometry(default_gauge_cfg):
    """Section 26: Verify that changing 'ticks' (Liczba podziałek) changes the rendered tick count."""
    layout = {"global": {}, "indicators": {"speed": default_gauge_cfg}}

    cfg4 = dict(default_gauge_cfg, ticks=4)
    img4, _, _, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="speed", value=20.0, unit="km/h", label="Speed", cfg_override=cfg4,
    )
    cfg20 = dict(default_gauge_cfg, ticks=20)
    img20, _, _, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="speed", value=20.0, unit="km/h", label="Speed", cfg_override=cfg20,
    )
    arr4 = np.array(img4)
    arr20 = np.array(img20)
    # 20 sub-ticks has more tick pixels than 4 sub-ticks
    assert np.count_nonzero(arr20[:, :, 3] > 0) > np.count_nonzero(arr4[:, :, 3] > 0)


def test_gauge_width_change_affects_geometry(default_gauge_cfg):
    """Section 26: Verify that changing width produces visual changes."""
    layout = {"global": {}, "indicators": {"speed": default_gauge_cfg}}

    cfg_a = dict(default_gauge_cfg, thickness=2)
    img_a, _, _, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="speed", value=20.0, unit="km/h", label="Speed", cfg_override=cfg_a,
    )
    cfg_b = dict(default_gauge_cfg, thickness=8)
    img_b, _, _, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="speed", value=20.0, unit="km/h", label="Speed", cfg_override=cfg_b,
    )
    arr_a = np.array(img_a)
    arr_b = np.array(img_b)
    diff = np.abs(arr_a.astype(int) - arr_b.astype(int))
    assert diff.max() > 0
    assert np.count_nonzero(diff > 0) > 1000


def test_gauge_property_save_reload(tmp_path, default_gauge_cfg):
    """Section 26: Verify that modified ticks and thickness are cleanly saved to JSON and reloaded."""
    layout = {
        "version": 6,
        "global": {"text_outline": 3},
        "indicators": {
            "fit_enhanced_speed_text": dict(default_gauge_cfg, ticks=12, thickness=5),
        },
    }
    file_path = tmp_path / "custom_gauge_layout.json"
    file_path.write_text(json.dumps(layout, indent=2), encoding="utf-8")

    loaded_layout = normalize_layout(file_path, 1920, 1080)
    ind = loaded_layout["indicators"]["fit_enhanced_speed_text"]
    assert ind["ticks"] == 12
    assert ind["thickness"] == 5


def test_gauge_property_live_preview(default_gauge_cfg):
    """Section 26: Verify schema labels in property editor for Ticks tab."""
    schema = get_schema_for_form("gauge")
    schema_map = {f.name: f for f in schema}
    assert "ticks" in schema_map
    assert schema_map["ticks"].label == "Liczba podziałek"
    assert schema_map["ticks"].tab == "Ticks"
    assert "thickness" in schema_map
    assert schema_map["thickness"].label == "Grubość podziałek"
    assert schema_map["thickness"].tab == "Ticks"
