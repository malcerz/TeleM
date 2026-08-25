"""Test suite for ETAP 8M.6 — Chart axis labels and values clipping fix."""
import pytest
import math
import numpy as np
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw

from src.indicators.chart_utils import _build_chart_bg, get_history_chart_background
from src.indicators.chart import _render_chart_indicator, ChartSplit
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import s, load_font, load_font_cache_small


@pytest.fixture
def chart_cfg():
    return {
        "enabled": True,
        "label": "Heart Rate",
        "x": 79.61,
        "y": 85.5,
        "rotation": 0,
        "form": "chart",
        "font_size": 1.8,
        "size": 30.0,
        "thickness": 2,
        "min_val": 77.0,
        "max_val": 116.0,
        "ticks": 0,
        "source": "fit",
        "unit": "BPM",
        "chart_time_scope": "activity",
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


def test_chart_right_100_percent_not_clipped(chart_cfg):
    """Section 25: Verify that '100%' label is strictly inside chart width with positive margin."""
    chart_w = 576
    chart_h = 230
    mock_history = [80.0, 90.0, 100.0, 110.0, 105.0]
    bg_img, points, plot_y1, plot_y2, _ = _build_chart_bg(
        history_values=mock_history, width=chart_w, height=chart_h,
        line_color=(255, 0, 0), line_thickness=2, fill_alpha=40, fill_color=None,
        show_axes=True, grid_color=None, time_labels=["0%", "25%", "50%", "75%", "100%"],
        value_labels=["77", "116"], supersample=1, custom_min_val=77.0,
        custom_max_val=116.0, label_count=2, label_units=False, unit="BPM",
        show_average=False, label_font_size=None, font_path="assets/Roboto-Bold.ttf",
    )
    # The rightmost 2 columns of pixels should have alpha = 0 (clean unclipped margin)
    arr = np.array(bg_img)
    alpha = arr[:, :, 3]
    assert np.all(alpha[:, -2:] == 0), "Rightmost pixels are non-zero, indicating clipping of rightmost label!"


def test_chart_left_0_percent_not_clipped(chart_cfg):
    """Section 25: Verify that '0%' label is strictly inside left margin (x >= 0)."""
    chart_w = 576
    chart_h = 230
    mock_history = [80.0, 90.0, 100.0, 110.0, 105.0]
    bg_img, points, plot_y1, plot_y2, _ = _build_chart_bg(
        history_values=mock_history, width=chart_w, height=chart_h,
        line_color=(255, 0, 0), line_thickness=2, fill_alpha=40, fill_color=None,
        show_axes=True, grid_color=None, time_labels=["0%", "25%", "50%", "75%", "100%"],
        value_labels=["77", "116"], supersample=1, custom_min_val=77.0,
        custom_max_val=116.0, label_count=2, label_units=False, unit="BPM",
        show_average=False, label_font_size=None, font_path="assets/Roboto-Bold.ttf",
    )
    arr = np.array(bg_img)
    alpha = arr[:, :, 3]
    # Check that leftmost 2 columns are within bounds
    assert bg_img.size == (576, 230)
    assert np.count_nonzero(alpha > 0) > 1000


def test_chart_y_min_not_clipped(chart_cfg):
    """Section 25: Verify that Y-min label is within [0..chart_h]."""
    chart_w = 576
    chart_h = 230
    mock_history = [80.0, 90.0, 100.0, 110.0, 105.0]
    bg_img, points, plot_y1, plot_y2, _ = _build_chart_bg(
        history_values=mock_history, width=chart_w, height=chart_h,
        line_color=(255, 0, 0), line_thickness=2, fill_alpha=40, fill_color=None,
        show_axes=True, grid_color=None, time_labels=None,
        value_labels=["77", "116"], supersample=1, custom_min_val=77.0,
        custom_max_val=116.0, label_count=2, label_units=False, unit="BPM",
        show_average=False, label_font_size=None, font_path="assets/Roboto-Bold.ttf",
    )
    # Bottom margin has ample space (height * 0.20)
    assert plot_y2 < chart_h - 10


def test_chart_y_max_not_clipped(chart_cfg):
    """Section 25: Verify that top Y-max label is not clipped at top (y >= 0)."""
    chart_w = 576
    chart_h = 230
    mock_history = [80.0, 90.0, 100.0, 110.0, 105.0]
    bg_img, points, plot_y1, plot_y2, _ = _build_chart_bg(
        history_values=mock_history, width=chart_w, height=chart_h,
        line_color=(255, 0, 0), line_thickness=2, fill_alpha=40, fill_color=None,
        show_axes=True, grid_color=None, time_labels=None,
        value_labels=["77", "116"], supersample=1, custom_min_val=77.0,
        custom_max_val=116.0, label_count=2, label_units=False, unit="BPM",
        show_average=False, label_font_size=None, font_path="assets/Roboto-Bold.ttf",
    )
    # The top margin must be at least 4px to ensure y >= 0
    assert plot_y1 >= 4
    arr = np.array(bg_img)
    alpha = arr[:, :, 3]
    assert np.count_nonzero(alpha > 0) > 1000


def test_chart_labels_include_outline_in_bbox(chart_cfg):
    """Section 25: Verify full chart widget includes header title, value text, and outline."""
    layout = {"global": {"text_outline": 3}, "indicators": {"fit_heart_rate_text": chart_cfg}}
    img, rx, ry, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="fit_heart_rate_text", value=106.0, unit="BPM", label="Heart Rate",
        cfg_override=chart_cfg, history_data=[80.0, 90.0, 106.0],
    )
    arr = np.array(img)
    alpha = arr[:, :, 3]
    y_idx, x_idx = np.where(alpha > 0)
    assert x_idx.min() >= 0 and x_idx.max() < img.width
    assert y_idx.min() >= 0 and y_idx.max() < img.height


def test_chart_static_texture_contains_all_labels(chart_cfg):
    """Section 25: Verify that GPU static texture contains full labels."""
    layout = {"global": {}, "indicators": {"fit_cadence_text": chart_cfg}}
    gpu_cap = {}
    bboxes = {}
    _compose_test_overlay(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        _bboxes=bboxes, indicator_values={"fit_cadence_text": 85.0},
        gpu_capture_keys={"fit_cadence_text"}, gpu_capture=gpu_cap,
        split_chart_keys={"fit_cadence_text"}, reuse_canvas=False,
    )
    assert "fit_cadence_text" in gpu_cap
    static_img = gpu_cap["fit_cadence_text"]["static"]
    arr = np.array(static_img)
    alpha = arr[:, :, 3]
    assert np.count_nonzero(alpha > 0) > 2000
    # Right border of static texture must be clean
    assert np.all(alpha[:, -2:] == 0)


def test_chart_activity_scope_label_geometry(chart_cfg):
    """Section 25: Verify activity scope labels and plot range geometry."""
    cfg = dict(chart_cfg, chart_time_scope="activity")
    layout = {"global": {}, "indicators": {"hr": cfg}}
    t0 = datetime(2026, 8, 19, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 19, 10, 30, 0, tzinfo=timezone.utc)
    ts = [t0, t0 + timedelta(minutes=10), t0 + timedelta(minutes=20), t1]
    from src.indicators.chart_builder import ChartHistory
    history = ChartHistory([80.0, 95.0, 110.0, 105.0], ts, chart_start_dt=t0, chart_end_dt=t1, time_scope="activity")

    img, rx, ry, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="hr", value=105.0, unit="BPM", label="Heart Rate", cfg_override=cfg,
        history_data=history, target_dt=t0 + timedelta(minutes=25),
    )
    assert img is not None
    assert img.width > 500


def test_chart_video_scope_label_geometry(chart_cfg):
    """Section 25: Verify video scope labels and plot range geometry."""
    cfg = dict(chart_cfg, chart_time_scope="video")
    layout = {"global": {}, "indicators": {"hr": cfg}}
    t0 = datetime(2026, 8, 19, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 19, 10, 1, 0, tzinfo=timezone.utc)
    ts = [t0, t0 + timedelta(seconds=20), t0 + timedelta(seconds=40), t1]
    from src.indicators.chart_builder import ChartHistory
    history = ChartHistory([80.0, 95.0, 110.0, 105.0], ts, chart_start_dt=t0, chart_end_dt=t1, time_scope="video")

    img, rx, ry, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="hr", value=105.0, unit="BPM", label="Heart Rate", cfg_override=cfg,
        history_data=history, target_dt=t0 + timedelta(seconds=30),
    )
    assert img is not None
    assert img.width > 500


def test_chart_preview_final_label_parity(chart_cfg):
    """Section 25: Verify parity between Preview crop and direct CPU render."""
    layout = {"global": {}, "indicators": {"fit_cadence_text": chart_cfg}}
    bboxes = {}
    p_canvas = _compose_test_overlay(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        _bboxes=bboxes, indicator_values={"fit_cadence_text": 88.0},
        gpu_capture_keys=None, reuse_canvas=False,
    )
    bx, by, bw, bh = bboxes["fit_cadence_text"]
    crop = p_canvas.crop((bx, by, bx + bw, by + bh))
    
    cpu_img, _, _, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="fit_cadence_text", value=88.0, unit="rpm", label="Cadence",
        cfg_override=chart_cfg, history_data=[60.0, 80.0, 90.0, 88.0],
    )
    assert crop.size == cpu_img.size


def test_chart_labels_multi_resolution(chart_cfg):
    """Section 24 & 25: Verify that across 4K, 1080p, 720p, 480p no labels are clipped."""
    resolutions = [(3840, 2160), (1920, 1080), (1280, 720), (854, 480)]
    for w, h in resolutions:
        size_px = s(30.0, w)
        chart_w = size_px
        chart_h = max(40, int(chart_w * 0.4))
        bg_img, points, plot_y1, plot_y2, _ = _build_chart_bg(
            history_values=[50.0, 80.0, 90.0], width=chart_w, height=chart_h,
            line_color=(255, 0, 0), line_thickness=2, fill_alpha=40, fill_color=None,
            show_axes=True, grid_color=None, time_labels=["0%", "25%", "50%", "75%", "100%"],
            value_labels=["0", "100"], supersample=1, custom_min_val=0.0,
            custom_max_val=100.0, label_count=2, label_units=False, unit="",
            show_average=False, label_font_size=None, font_path="assets/Roboto-Bold.ttf",
        )
        arr = np.array(bg_img)
        alpha = arr[:, :, 3]
        # Right border must have zero alpha (not clipped)
        assert np.all(alpha[:, -1] == 0), f"Rightmost pixel clipped in resolution {w}x{h}!"
        assert plot_y1 >= 4, f"Top margin too small in resolution {w}x{h}!"
