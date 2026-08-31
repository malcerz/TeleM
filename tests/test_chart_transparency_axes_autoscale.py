from __future__ import annotations

from src.indicators.chart import _window_time_labels
from src.indicators.chart_utils import (
    generate_history_chart,
    generate_nice_relative_time_ticks,
    generate_nice_value_ticks,
    get_history_chart_background,
)


def test_fill_alpha_changes_fill_only_not_chart_structure_or_line():
    kwargs = dict(
        line_color=(0, 170, 255),
        line_thickness=2,
        fill_color=(0, 170, 255),
        show_axes=True,
        grid_color=(68, 68, 68, 120),
        custom_min_val=0.0,
        custom_max_val=100.0,
        label_count=3,
        axis_font_size=12,
        axis_outline=2,
    )
    low = generate_history_chart([10, 60, 90], 320, 180, fill_alpha=20, **kwargs)
    high = generate_history_chart([10, 60, 90], 320, 180, fill_alpha=200, **kwargs)
    _, points, plot_y1, plot_y2, _, _ = get_history_chart_background(
        [10, 60, 90], 320, 180, fill_alpha=20, **kwargs,
    )

    # The opaque polyline and the structural axes remain byte-identical.
    for x, y in points:
        ix, iy = round(x), round(y)
        assert low.getpixel((ix, iy)) == high.getpixel((ix, iy))
    for x, y in ((points[0][0], plot_y1), (points[0][0], plot_y2)):
        ix, iy = round(x), round(y)
        assert low.getpixel((ix, iy)) == high.getpixel((ix, iy))
    grid_x = round((points[0][0] + points[-1][0]) / 2)
    grid_y = round(plot_y1 + (plot_y2 - plot_y1) / 2)
    assert low.getpixel((grid_x, grid_y)) == high.getpixel((grid_x, grid_y))

    # A point in the series area demonstrates that alpha still has an effect.
    assert low.tobytes() != high.tobytes()


def test_auto_value_ticks_pad_data_and_keep_points_inside_domain():
    lo, hi, labels = generate_nice_value_ticks(73, 117, 5)
    assert lo <= 73 < 117 <= hi
    assert labels[0] == str(int(lo))
    assert labels[-1] == str(int(hi))

    _, points, plot_y1, plot_y2, _, _ = get_history_chart_background(
        [73, 117], 320, 180, fill_alpha=40, label_count=5,
    )
    assert plot_y1 <= min(y for _x, y in points)
    assert max(y for _x, y in points) <= plot_y2


def test_window_time_ticks_are_nice_and_time_accurate():
    ticks = generate_nice_relative_time_ticks(60)
    assert [label for _norm, label in ticks] == _window_time_labels(60)
    assert ticks == [
        (0.0, "-60 s"), (0.25, "-45 s"), (0.5, "-30 s"),
        (0.75, "-15 s"), (1.0, "0 s"),
    ]

    irregular = generate_nice_relative_time_ticks(70)
    assert irregular[0][1] == "-70 s"
    assert irregular[-1] == (1.0, "0 s")
    assert all(0.0 <= norm <= 1.0 for norm, _label in irregular)
