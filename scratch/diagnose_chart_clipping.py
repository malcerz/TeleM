"""Measure exact bounding boxes and detect clipping for Cadence and Heart Rate charts."""
import sys
import math
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.chart_utils import _build_chart_bg, get_history_chart_background
from src.indicators.chart import _render_chart_indicator
from src.indicators.chart_builder import build_chart_data
from src.gui.layout_manager import normalize_layout
from src.indicators.helpers import s, load_font, load_font_cache_small

out_dir = root / "Raporty" / "etap8m6_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

# Load layout
layout = normalize_layout(root / "def_layout.json", 1920, 1080)
font_path = "assets/Roboto-Bold.ttf"

for key in ["fit_cadence_text", "fit_heart_rate_text"]:
    cfg = layout["indicators"][key]
    canvas_w, canvas_h = 1920, 1080
    min_dim = 1080
    size_px = s(cfg["size"], canvas_w)
    fs = max(8, s(cfg["font_size"], min_dim))
    chart_w = size_px
    chart_h = max(40, int(chart_w * 0.4))
    
    print(f"\n==================== {key} ====================")
    print(f"Canvas: {canvas_w}x{canvas_h}, size={cfg['size']}%, size_px={size_px}, chart_w={chart_w}, chart_h={chart_h}, fs={fs}")

    # Inspect _build_chart_bg directly
    mock_history = [20.0, 50.0, 80.0, 60.0, 40.0, 75.0, 90.0]
    bg_img, points, plot_y1, plot_y2, calc_thickness = _build_chart_bg(
        history_values=mock_history,
        width=chart_w,
        height=chart_h,
        line_color=(255, 0, 0),
        line_thickness=2,
        fill_alpha=40,
        fill_color=None,
        show_axes=True,
        grid_color=(68, 68, 68, 60),
        time_labels=None,
        value_labels=None,
        supersample=1,
        custom_min_val=float(cfg.get("min_val", 0)),
        custom_max_val=float(cfg.get("max_val", 100)),
        label_count=int(cfg.get("label_count", 2)),
        label_units=bool(cfg.get("label_units", False)),
        unit=cfg.get("unit", ""),
        show_average=bool(cfg.get("show_average", False)),
        label_font_size=None,
        font_path=font_path,
    )

    # Let's inspect the exact positions of labels
    draw = ImageDraw.Draw(bg_img)
    axis_top_margin = 4
    axis_right_margin = 4
    axis_bottom_margin = int(max(6, chart_h * 0.20))
    plot_h_est = max(1, chart_h - axis_top_margin - axis_bottom_margin)
    label_fs = int(max(7, min(chart_w, chart_h) * 0.13))
    label_fs = max(6, min(label_fs, max(6, plot_h_est // 2)))
    font_axis = load_font(font_path, label_fs) if font_path else load_font_cache_small(label_fs)

    # Measure 100%
    x_labels = ["0%", "25%", "50%", "75%", "100%"]
    count = max(2, int(cfg.get("label_count", 2)))
    min_val = float(cfg.get("min_val", 0))
    max_val = float(cfg.get("max_val", 100))
    val_range = max_val - min_val
    y_label_values = [f"{min_val + (i / (count - 1)) * val_range:.0f}" for i in range(count)]

    max_label_w = max(draw.textbbox((0, 0), lbl, font=font_axis)[2] for lbl in y_label_values)
    l_bbox = draw.textbbox((0, 0), x_labels[0], font=font_axis)
    left_hw = (l_bbox[2] - l_bbox[0]) / 2.0
    r_bbox = draw.textbbox((0, 0), x_labels[-1], font=font_axis)
    right_hw = (r_bbox[2] - r_bbox[0]) / 2.0
    axis_left_margin = int(math.ceil(max(max_label_w + 10, left_hw + 4)))
    axis_right_margin = int(math.ceil(right_hw + 4))

    plot_x1 = axis_left_margin
    plot_x2 = chart_w - axis_right_margin
    plot_w = max(1, plot_x2 - plot_x1)

    print(f"plot_x1={plot_x1}, plot_x2={plot_x2}, plot_w={plot_w}, plot_y1={plot_y1}, plot_y2={plot_y2}")
    print(f"axis_left_margin={axis_left_margin}, axis_right_margin={axis_right_margin}, axis_top_margin={plot_y1}")
    print(f"label_fs={label_fs}")

    print("\n--- X-Axis Labels Positions & Bounds ---")
    for i, lbl in enumerate(x_labels):
        x = plot_x1 + (plot_w * i / max(1, len(x_labels) - 1))
        bbox = draw.textbbox((0, 0), lbl, font=font_axis)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = x - tw // 2
        ty = plot_y2 + 5
        text_left = tx + bbox[0]
        text_right = tx + bbox[2]
        is_clipped = (text_left < 0) or (text_right > chart_w)
        print(f"Label '{lbl:>4}': anchor_x={x:6.1f}, tw={tw:2d}, tx={tx:6.1f}, text_left={text_left:6.1f}, text_right={text_right:6.1f}, chart_w={chart_w} -> CLIPPED: {is_clipped} (overflow={text_right - chart_w:+.1f}px)")

    print("\n--- Y-Axis Labels Positions & Bounds ---")
    y_positions = [
        plot_y2 - (i / max(1, len(y_label_values) - 1)) * (plot_y2 - plot_y1)
        for i in range(len(y_label_values))
    ]
    for lbl, yp in zip(y_label_values, y_positions):
        bbox = draw.textbbox((0, 0), lbl, font=font_axis)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = plot_x1 - tw - 5
        ty = yp - th // 2
        text_top = ty + bbox[1]
        text_bottom = ty + bbox[3]
        is_clipped_top = text_top < 0
        is_clipped_bottom = text_bottom > chart_h
        print(f"Y-Label '{lbl:>4}': yp={yp:6.1f}, th={th:2d}, ty={ty:6.1f}, text_top={text_top:6.1f}, text_bottom={text_bottom:6.1f}, chart_h={chart_h} -> CLIPPED: {is_clipped_top or is_clipped_bottom} (top_overflow={-text_top:+.1f}px)")
