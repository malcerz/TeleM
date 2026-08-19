"""
Test with accurate max(bbox[3]) vertical extent.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path("c:/_DEV/TeleM")))

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import math

def build_chart_bg_robust(
    history_values, width, height, line_color, line_thickness,
    fill_alpha, fill_color, show_axes, grid_color, time_labels,
    value_labels, supersample, custom_min_val, custom_max_val,
    label_count, label_units, unit, show_average, label_font_size,
    font_path,
):
    ss = max(1, int(supersample))
    out_w, out_h = width, height
    width *= ss
    height *= ss
    calc_line_thickness = line_thickness * ss
    has_data = history_values and len(history_values) >= 2

    if has_data:
        data_min = float(min(history_values))
        data_max = float(max(history_values))
    else:
        data_min = 0.0
        data_max = 100.0

    min_val = custom_min_val if custom_min_val is not None else data_min
    max_val = custom_max_val if custom_max_val is not None else data_max
    if min_val >= max_val:
        max_val = min_val + 1.0

    val_range = max_val - min_val

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    count = max(2, label_count)
    y_label_values = value_labels if value_labels else [
        f"{min_val + (i / (count - 1)) * val_range:.0f}"
        + (f" {unit}" if (label_units and unit) else "")
        for i in range(count)
    ]
    x_labels = time_labels if time_labels else ["0%", "25%", "50%", "75%", "100%"]

    axis_bottom_margin_est = (int(max(6, height * 0.18)) if show_axes else 0) * ss
    try:
        plot_h_est = max(1, height - 4 * ss - axis_bottom_margin_est)
        if label_font_size and label_font_size > 0:
            label_fs = int(label_font_size * ss)
        else:
            label_fs = int(max(7, min(width, height) * 0.12) * ss)
        label_fs = max(6, min(label_fs, max(6, plot_h_est // 2)))
        if font_path:
            from src.indicators.helpers import load_font
            font_axis = load_font(font_path, label_fs)
        else:
            from src.indicators.helpers import load_font_cache_small
            font_axis = load_font_cache_small(label_fs)
    except Exception:
        font_axis = None

    if show_axes:
        max_label_w = 0
        max_y_bot = 0
        max_y_top = 0
        for lbl in y_label_values:
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                max_y_bot = max(max_y_bot, bbox[3])
                max_y_top = max(max_y_top, -bbox[1] if bbox[1] < 0 else 0)
            else:
                tw = len(lbl) * 6
                th = 10
                max_y_bot = max(max_y_bot, 10)
            max_label_w = max(max_label_w, tw)

        max_x_bot = 0
        max_x_label_w = 0
        for lbl in x_labels:
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                max_x_bot = max(max_x_bot, bbox[3])
                max_x_label_w = max(max_x_label_w, bbox[2] - bbox[0])
            else:
                max_x_bot = max(max_x_bot, 10)
                max_x_label_w = max(max_x_label_w, len(lbl) * 6)

        axis_left_margin = int(math.ceil(max_label_w + 8 * ss + 2 * ss))
        axis_right_margin = int(math.ceil(max(6 * ss, max_x_label_w // 2 + 4 * ss)))
        axis_top_margin = int(math.ceil(max(4 * ss, max_y_bot / 2.0 + max_y_top + 4 * ss)))
        needed_bottom_margin = int(math.ceil(max_x_bot + 10 * ss))
        axis_bottom_margin = max(axis_bottom_margin_est, needed_bottom_margin)
    else:
        axis_left_margin = 0
        axis_right_margin = 4 * ss
        axis_top_margin = 4 * ss
        axis_bottom_margin = 4 * ss

    plot_x1 = axis_left_margin
    plot_y1 = axis_top_margin
    plot_x2 = width - axis_right_margin
    plot_y2 = height - axis_bottom_margin
    plot_w = max(1, plot_x2 - plot_x1)
    plot_h = max(1, plot_y2 - plot_y1)

    if show_axes:
        axis_color = (180, 180, 180, 220)
        tick_color = (150, 150, 150, 200)
        label_color = (200, 200, 200, 240)

        draw.line((plot_x1, plot_y1, plot_x1, plot_y2), fill=axis_color, width=max(1, ss))
        draw.line((plot_x1, plot_y2, plot_x2, plot_y2), fill=axis_color, width=max(1, ss))

        y_positions = [
            plot_y2 - (i / max(1, len(y_label_values) - 1)) * plot_h
            for i in range(len(y_label_values))
        ]

        for lbl, yp in zip(y_label_values, y_positions):
            if grid_color is not None:
                draw.line((plot_x1, yp, plot_x2, yp), fill=grid_color, width=max(1, ss))
            draw.line((plot_x1 - 4 * ss, yp, plot_x1, yp), fill=tick_color, width=max(1, ss))
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                b_bot = bbox[3]
                b_top = bbox[1]
            else:
                tw = len(lbl) * 6
                th = 10
                b_bot = 10
                b_top = 0
            tx = max(2 * ss, plot_x1 - tw - 5 * ss)
            ty = int(round(yp - (b_bot + b_top) / 2.0))
            ty = max(2 * ss - b_top, min(height - b_bot - 2 * ss, ty))
            if font_axis:
                draw.text((tx, ty), lbl, fill=label_color, font=font_axis)
            else:
                draw.text((tx, ty), lbl, fill=label_color)

        for i, lbl in enumerate(x_labels):
            x = plot_x1 + (plot_w * i / max(1, len(x_labels) - 1))
            draw.line((x, plot_y2, x, plot_y2 + 4 * ss), fill=tick_color, width=max(1, ss))
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                tw = bbox[2] - bbox[0]
                b_bot = bbox[3]
            else:
                tw = len(lbl) * 6
                bbox = (0, 0, tw, 10)
                b_bot = 10
            
            if i == 0:
                tx = max(2 * ss, int(round(x - max(0, bbox[0]))))
            elif i == len(x_labels) - 1:
                tx = min(width - tw - 2 * ss, int(round(x - tw)))
            else:
                tx = int(round(x - tw / 2.0))
                tx = max(2 * ss, min(width - tw - 2 * ss, tx))
            
            ty = plot_y2 + 5 * ss
            ty = min(height - b_bot - 2 * ss, ty)
            if font_axis:
                draw.text((tx, ty), lbl, fill=label_color, font=font_axis)
            else:
                draw.text((tx, ty), lbl, fill=label_color)

    return img

print("Running robust test across extensive permutations...")
failed = 0
total = 0
for w in [300, 500, 800, 1152, 1600]:
    for h in [80, 120, 200, 300, 460, 600]:
        for lfs in [None, 10, 18, 28, 36]:
            for x_lbls in [['0%', '25%', '50%', '75%', '100%'], ['00:00', '10:00', '20:00'], ['00:00:00', '01:00:00']]:
                for y_lbls in [['0', '100'], ['0 bpm', '100 bpm', '200 bpm'], ['-500 m', '0 m', '+500 m']]:
                    total += 1
                    img = build_chart_bg_robust(
                        list(range(50)), w, h, (255,255,0), 1, 200, None, True, None,
                        x_lbls, y_lbls, 1, 0, 100, len(y_lbls), True, '', False, lfs, 'arial.ttf'
                    )
                    arr = np.array(img)
                    a = arr[:, :, 3]
                    nz_y, nz_x = np.nonzero(a > 0)
                    if len(nz_y) > 0:
                        min_y, max_y = np.min(nz_y), np.max(nz_y)
                        min_x, max_x = np.min(nz_x), np.max(nz_x)
                        if min_x == 0 or max_x == w - 1 or min_y == 0 or max_y == h - 1:
                            failed += 1
                            print(f"FAILED on w={w}, h={h}, lfs={lfs}, x={x_lbls[-1]}, y={y_lbls[-1]}: X=[{min_x}, {max_x}]/{w}, Y=[{min_y}, {max_y}]/{h}")

print(f"RESULTS: {total - failed}/{total} passed (Failed={failed})")
