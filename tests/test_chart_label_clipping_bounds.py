"""
Regression tests for automatic chart label clipping detection (ETAP 9 USER BUG FIX).

Verifies that for small, standard, and large charts at 4K and 1080p:
- X tick labels (0%, 25%, 50%, 75%, 100%, timestamps)
- Y tick labels (min, mid, max, units)
- Title and value text
have strictly non-negative left/top margins and never touch or exceed visual raster borders:
x0 >= 0, y0 >= 0, x1 <= raster_width, y1 <= raster_height.
"""
import pytest
from PIL import Image
import numpy as np

from src.indicators.chart_utils import _build_chart_bg, generate_history_chart
from src.indicators.chart import _render_chart_indicator
from src.gui.layout_manager import normalize_layout
from src.indicators.helpers import s


@pytest.mark.parametrize("canvas_w, canvas_h", [
    (3840, 2160),
    (1920, 1080),
])
@pytest.mark.parametrize("chart_key", [
    "fit_cadence_text",
    "fit_heart_rate_text",
])
def test_production_chart_labels_within_bounds(canvas_w, canvas_h, chart_key):
    layout = normalize_layout("def_layout.json", canvas_w, canvas_h)
    cfg = layout["indicators"][chart_key]
    min_dim = min(canvas_w, canvas_h)
    chart_w = s(cfg.get("size", 0.3), canvas_w)
    
    vals = [50.0 + (i * 13) % 40 for i in range(100)]
    res, rx, ry, _ = _render_chart_indicator(
        canvas_w=canvas_w, canvas_h=canvas_h, layout=layout,
        font_path="assets/Roboto-Bold.ttf",
        key=chart_key, value=64.0, unit="rpm", label=cfg.get("label", "Chart"),
        cfg=cfg, min_dim=min_dim, outline=max(1, int(min_dim * 0.002)), fs=int(min_dim * 0.018),
        font=None, val_min=cfg.get("min_val", 0), val_max=cfg.get("max_val", 100),
        ticks=[], thickness=2, size_px=chart_w, ss=1,
        history_data=vals, formatted_val="64 rpm", split_mode=True,
    )
    
    static_img = res.static
    arr = np.array(static_img)
    alpha = arr[:, :, 3]
    h, w = alpha.shape
    nz_y, nz_x = np.nonzero(alpha > 0)
    assert len(nz_y) > 0, "Static image has no non-transparent content"
    
    min_y, max_y = int(np.min(nz_y)), int(np.max(nz_y))
    min_x, max_x = int(np.min(nz_x)), int(np.max(nz_x))
    
    # Assert strict containment: x0 >= 0, y0 >= 0, x1 < w, y1 < h
    assert min_x >= 0, f"Left overflow in {chart_key} ({canvas_w}x{canvas_h}): min_x={min_x}"
    assert min_y >= 0, f"Top overflow in {chart_key} ({canvas_w}x{canvas_h}): min_y={min_y}"
    assert max_x < w - 1, f"Right clipping in {chart_key} ({canvas_w}x{canvas_h}): max_x={max_x} >= {w-1}"
    assert max_y < h - 1, f"Bottom clipping in {chart_key} ({canvas_w}x{canvas_h}): max_y={max_y} >= {h-1}"


@pytest.mark.parametrize("width, height", [
    (300, 120),
    (600, 240),
    (1152, 460),
    (1600, 600),
])
@pytest.mark.parametrize("time_labels", [
    ["0%", "25%", "50%", "75%", "100%"],
    ["00:00", "10:00", "20:00", "30:00"],
    ["00:00:00", "01:00:00", "02:00:00"],
])
@pytest.mark.parametrize("value_labels", [
    ["0", "50", "100"],
    ["0 bpm", "100 bpm", "200 bpm"],
    ["-500 m", "0 m", "+500 m"],
])
def test_chart_bg_all_permutations_within_bounds(width, height, time_labels, value_labels):
    bg_img, points, p1, p2, _ = _build_chart_bg(
        history_values=list(range(50)),
        width=width,
        height=height,
        line_color=(255, 255, 0),
        line_thickness=1,
        fill_alpha=200,
        fill_color=(255, 255, 127),
        show_axes=True,
        grid_color=(68, 68, 68, 60),
        time_labels=time_labels,
        value_labels=value_labels,
        supersample=1,
        custom_min_val=0.0,
        custom_max_val=100.0,
        label_count=len(value_labels),
        label_units=True,
        unit="",
        show_average=False,
        label_font_size=None,
        font_path="assets/Roboto-Bold.ttf",
    )
    
    arr = np.array(bg_img)
    alpha = arr[:, :, 3]
    h, w = alpha.shape
    nz_y, nz_x = np.nonzero(alpha > 0)
    assert len(nz_y) > 0
    
    min_y, max_y = int(np.min(nz_y)), int(np.max(nz_y))
    min_x, max_x = int(np.min(nz_x)), int(np.max(nz_x))
    
    assert min_x >= 0
    assert min_y >= 0
    assert max_x < w - 1, f"Right clipping: max_x={max_x} >= {w-1}"
    assert max_y < h - 1, f"Bottom clipping: max_y={max_y} >= {h-1}"
