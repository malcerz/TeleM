"""Chart generation utilities — standalone line chart rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

from typing import Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import load_font, load_font_cache_small


def generate_history_chart(
    history_values: list[float],
    width: int,
    height: int,
    line_color: tuple[int, int, int] = (255, 0, 0),
    line_thickness: int = 3,
    fill_alpha: int = 50,
    fill_color: Optional[tuple[int, int, int]] = None,
    current_index: Optional[int] = None,
    cursor_color: tuple[int, int, int] = (255, 255, 255),
    show_axes: bool = True,
    grid_color: Optional[tuple[int, int, int, int]] = None,
    time_labels: Optional[list[str]] = None,
    value_labels: Optional[list[str]] = None,
    supersample: int = 1,
    custom_min_val: Optional[float] = None,
    custom_max_val: Optional[float] = None,
    label_count: int = 2,
    label_units: bool = False,
    unit: str = "",
    show_average: bool = False,
    label_font_size: Optional[float] = None,
    font_path: Optional[str] = None,
) -> Image.Image:
    """Generate a universal line chart with transparent fill, axes, and optional cursor."""
    ss = max(1, int(supersample))
    out_w, out_h = width, height
    width *= ss
    height *= ss
    line_thickness *= ss
    ss = max(1, int(supersample))
    out_w, out_h = width, height
    width *= ss
    height *= ss
    line_thickness *= ss
    axis_top_margin = 4 * ss
    axis_right_margin = 4 * ss
    # Bottom margin scales with the chart height (for x-axis tick labels).
    axis_bottom_margin = (int(max(6, height * 0.20)) if show_axes else 0) * ss

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

    num_points = len(history_values) if has_data else 0

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Y-axis label values (before the left margin, so the margin can fit
    #    the widest label and proportions hold at any chart size) ─────────
    count = max(2, label_count)
    y_label_values = value_labels if value_labels else [
        f"{min_val + (i / (count - 1)) * val_range:.0f}"
        + (f" {unit}" if (label_units and unit) else "")
        for i in range(count)
    ]

    # Label font scales with the chart (honours explicit label_font_size px,
    # otherwise proportional to the smaller chart dimension).
    try:
        plot_h_est = max(1, height - axis_top_margin - axis_bottom_margin)
        if label_font_size and label_font_size > 0:
            label_fs = int(label_font_size * ss)
        else:
            label_fs = int(max(7, min(width, height) * 0.13) * ss)
        label_fs = max(6, min(label_fs, max(6, plot_h_est // 2)))
        if font_path:
            font_axis = load_font(font_path, label_fs)
        else:
            font_axis = load_font_cache_small(label_fs)
    except Exception:
        font_axis = None

    # Left margin sized to the widest Y-axis label so it never clips.
    if show_axes:
        max_label_w = 0
        for lbl in y_label_values:
            if font_axis:
                tw = draw.textbbox((0, 0), lbl, font=font_axis)[2]
            else:
                tw = len(lbl) * 6
            max_label_w = max(max_label_w, tw)
        axis_left_margin = int(max_label_w + 10)
    else:
        axis_left_margin = 0

    plot_x1 = axis_left_margin
    plot_y1 = axis_top_margin
    plot_x2 = width - axis_right_margin
    plot_y2 = height - axis_bottom_margin
    plot_w = plot_x2 - plot_x1
    plot_h = plot_y2 - plot_y1
    if plot_w <= 0:
        plot_w = 1
    if plot_h <= 0:
        plot_h = 1

    if show_axes:
        axis_color = (180, 180, 180, 220)
        tick_color = (150, 150, 150, 200)
        label_color = (200, 200, 200, 240)

        draw.line((plot_x1, plot_y1, plot_x1, plot_y2), fill=axis_color, width=1)
        draw.line((plot_x1, plot_y2, plot_x2, plot_y2), fill=axis_color, width=1)

        y_positions = [
            plot_y2 - (i / max(1, len(y_label_values) - 1)) * plot_h
            for i in range(len(y_label_values))
        ]

        # ── Horizontal grid lines & Y labels ──
        for lbl, yp in zip(y_label_values, y_positions):
            if grid_color is not None:
                draw.line((plot_x1, yp, plot_x2, yp), fill=grid_color, width=1)
            draw.line((plot_x1 - 4, yp, plot_x1, yp), fill=tick_color, width=1)
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            else:
                tw = len(lbl) * 6
                th = 10
            tx = plot_x1 - tw - 5
            ty = yp - th // 2
            if font_axis:
                draw.text((tx, ty), lbl, fill=label_color, font=font_axis)
            else:
                draw.text((tx, ty), lbl, fill=label_color)

        x_labels = time_labels if time_labels else ["0%", "25%", "50%", "75%", "100%"]
        for i, lbl in enumerate(x_labels):
            x = plot_x1 + (plot_w * i / max(1, len(x_labels) - 1))
            draw.line((x, plot_y2, x, plot_y2 + 4), fill=tick_color, width=1)
            if font_axis:
                bbox = draw.textbbox((0, 0), lbl, font=font_axis)
                tw = bbox[2] - bbox[0]
            else:
                tw = len(lbl) * 6
            tx = x - tw // 2
            ty = plot_y2 + 5
            if font_axis:
                draw.text((tx, ty), lbl, fill=label_color, font=font_axis)
            else:
                draw.text((tx, ty), lbl, fill=label_color)

    if not has_data:
        return img

    # Calculate point coordinates — mapped to the FULL plot height so that a
    # value of min_val/max_val lands exactly on the bottom/top axis label.
    points: list[tuple[float, float]] = []
    for i, val in enumerate(history_values):
        x = plot_x1 + (i / (num_points - 1)) * plot_w
        y = plot_y2 - ((val - min_val) / val_range) * plot_h
        points.append((x, y))

    # Fill under the line
    fill_polygon: list[tuple[float, float]] = list(points)
    fill_polygon.append((plot_x2, plot_y2))
    fill_polygon.append((plot_x1, plot_y2))
    # Fill under the line — draw directly on the main image
    actual_fill_rgb = fill_color if fill_color is not None else line_color
    actual_fill = (actual_fill_rgb[0], actual_fill_rgb[1], actual_fill_rgb[2], fill_alpha)

    draw.polygon(fill_polygon, fill=actual_fill)  # type: ignore[arg-type]

    # Redraw axes on top
    if show_axes:
        draw.line((plot_x1, plot_y1, plot_x1, plot_y2), fill=axis_color, width=1)
        draw.line((plot_x1, plot_y2, plot_x2, plot_y2), fill=axis_color, width=1)

    # Draw the line
    draw.line(points, fill=(line_color[0], line_color[1], line_color[2], 255), width=line_thickness, joint="round")

    # Draw average line
    if show_average and has_data:
        avg_val = float(sum(history_values) / len(history_values))
        if min_val <= avg_val <= max_val:
            avg_y = plot_y2 - ((avg_val - min_val) / val_range) * plot_h
            avg_color = (255, 200, 0, 220)
            for x in range(int(plot_x1), int(plot_x2), 6 * ss):
                draw.line((x, avg_y, min(x + 3 * ss, plot_x2), avg_y), fill=avg_color, width=max(1, ss))

    # Draw cursor
    if current_index is not None and 0 <= current_index < num_points:
        cursor_x = points[current_index][0]
        draw.line(
            (cursor_x, plot_y1, cursor_x, plot_y2),
            fill=(cursor_color[0], cursor_color[1], cursor_color[2], 200),
            width=max(2, line_thickness),
        )
        py = points[current_index][1]
        dot_r = max(3, line_thickness + 1)
        draw.ellipse(
            (cursor_x - dot_r, py - dot_r, cursor_x + dot_r, py + dot_r),
            fill=(cursor_color[0], cursor_color[1], cursor_color[2], 255),
            outline=(line_color[0], line_color[1], line_color[2], 255),
        )

    if ss > 1:
        img = img.resize((out_w, out_h), Image.LANCZOS)
    return img
