"""Test new margin calculation for chart_utils across resolutions and scopes."""
import math
import sys
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.helpers import s, load_font, load_font_cache_small

font_path = "assets/Roboto-Bold.ttf"

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

for w, h, res_name in resolutions:
    min_dim = min(w, h)
    size_pct = 30.0
    size_px = s(size_pct, w)
    chart_w = size_px
    chart_h = max(40, int(chart_w * 0.4))
    ss = 1
    
    img = Image.new("RGBA", (chart_w, chart_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Calculate label font size
    axis_bottom_margin_est = int(max(6, chart_h * 0.20)) * ss
    plot_h_est = max(1, chart_h - 4 * ss - axis_bottom_margin_est)
    label_fs = int(max(7, min(chart_w, chart_h) * 0.13) * ss)
    label_fs = max(6, min(label_fs, max(6, plot_h_est // 2)))
    font_axis = load_font(font_path, label_fs) if font_path else load_font_cache_small(label_fs)

    x_labels = ["0%", "25%", "50%", "75%", "100%"]
    y_label_values = ["77", "116"]  # HR example

    # Y-axis label dimensions
    max_label_w = 0
    max_label_h = 0
    for lbl in y_label_values:
        bbox = draw.textbbox((0, 0), lbl, font=font_axis)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        max_label_w = max(max_label_w, tw)
        max_label_h = max(max_label_h, th)
    
    # X-axis label dimensions
    left_x_label = x_labels[0]
    right_x_label = x_labels[-1]
    l_bbox = draw.textbbox((0, 0), left_x_label, font=font_axis)
    left_hw = (l_bbox[2] - l_bbox[0]) / 2.0
    r_bbox = draw.textbbox((0, 0), right_x_label, font=font_axis)
    right_hw = (r_bbox[2] - r_bbox[0]) / 2.0

    # Margins
    axis_left_margin = int(math.ceil(max(max_label_w + 10 * ss, left_hw + 4 * ss)))
    axis_right_margin = int(math.ceil(right_hw + 4 * ss))
    axis_top_margin = int(math.ceil(max(4 * ss, max_label_h / 2.0 + 2 * ss)))
    axis_bottom_margin = axis_bottom_margin_est

    plot_x1 = axis_left_margin
    plot_y1 = axis_top_margin
    plot_x2 = chart_w - axis_right_margin
    plot_y2 = chart_h - axis_bottom_margin
    plot_w = plot_x2 - plot_x1
    plot_h = plot_y2 - plot_y1

    print(f"\n[{res_name}] Canvas {w}x{h}, Chart {chart_w}x{chart_h}, label_fs={label_fs}")
    print(f"Margins: L={axis_left_margin}, R={axis_right_margin}, T={axis_top_margin}, B={axis_bottom_margin}")
    print(f"Plot rect: ({plot_x1}, {plot_y1}) -> ({plot_x2}, {plot_y2}), plot_w={plot_w}, plot_h={plot_h}")

    # Check all X labels
    for i, lbl in enumerate(x_labels):
        x = plot_x1 + (plot_w * i / max(1, len(x_labels) - 1))
        bbox = draw.textbbox((0, 0), lbl, font=font_axis)
        tw = bbox[2] - bbox[0]
        tx = x - tw // 2
        text_left = tx + bbox[0]
        text_right = tx + bbox[2]
        is_clipped = (text_left < 0) or (text_right > chart_w)
        assert not is_clipped, f"CLIPPED: {lbl} in {res_name}: left={text_left}, right={text_right}, chart_w={chart_w}"
        if i == len(x_labels) - 1:
            print(f"Rightmost label '{lbl}': anchor_x={x:.1f}, text_right={text_right:.1f}, chart_w={chart_w} (margin={chart_w - text_right:.1f}px >= 0) -> OK")

    # Check top Y label
    top_y = plot_y1
    top_lbl = y_label_values[-1]
    bbox = draw.textbbox((0, 0), top_lbl, font=font_axis)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = plot_x1 - tw - 5
    ty = top_y - th // 2
    text_top = ty + bbox[1]
    text_bottom = ty + bbox[3]
    is_clipped_top = text_top < 0
    assert not is_clipped_top, f"CLIPPED TOP Y LABEL: {top_lbl} in {res_name}: text_top={text_top}"
    print(f"Top Y-label '{top_lbl}': ty={ty:.1f}, text_top={text_top:.1f} >= 0 -> OK")
