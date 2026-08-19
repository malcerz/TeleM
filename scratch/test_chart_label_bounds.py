"""
Test extents of all chart labels (X labels, Y labels) against visual raster bounds.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path("c:/_DEV/TeleM")))

from PIL import Image, ImageDraw
import numpy as np

from src.indicators.chart_utils import _build_chart_bg
from src.indicators.chart import _render_chart_indicator
from src.gui.layout_manager import normalize_layout
from src.indicators.helpers import s

root = Path("c:/_DEV/TeleM")
layout = normalize_layout(root / "def_layout.json", 3840, 2160)

test_configs = [
    ("Cadence", layout["indicators"]["fit_cadence_text"], [60.0 + i % 30 for i in range(100)]),
    ("Heart Rate", layout["indicators"]["fit_heart_rate_text"], [120.0 + i % 40 for i in range(100)]),
    ("Small Chart", {"form": "chart", "size": 15.0, "x": 50, "y": 50, "label": "Small", "font_size": 1.5}, [10.0 + i for i in range(50)]),
    ("Large Chart", {"form": "chart", "size": 45.0, "x": 50, "y": 50, "label": "Large", "font_size": 2.5}, [10.0 + i for i in range(50)]),
]

for name, cfg, data in test_configs:
    chart_w = int(s(cfg.get("size", 0.3), 3840))
    chart_h = max(40, int(chart_w * 0.4))
    
    bg_img, points, plot_y1, plot_y2, calc_thickness = _build_chart_bg(
        history_values=data,
        width=chart_w,
        height=chart_h,
        line_color=(255, 255, 0),
        line_thickness=1,
        fill_alpha=200,
        fill_color=(255, 255, 127),
        show_axes=True,
        grid_color=(68, 68, 68, 60),
        time_labels=["0%", "25%", "50%", "75%", "100%"],
        value_labels=None,
        supersample=1,
        custom_min_val=0.0,
        custom_max_val=100.0,
        label_count=3,
        label_units=True,
        unit="rpm",
        show_average=False,
        label_font_size=0,
        font_path="assets/Roboto-Bold.ttf",
    )
    
    arr = np.array(bg_img)
    alpha = arr[:, :, 3]
    h, w = alpha.shape
    nz_y, nz_x = np.nonzero(alpha > 0)
    
    print(f"\n[{name}] bg_img: {w}x{h}, plot_y1={plot_y1}, plot_y2={plot_y2}")
    if len(nz_y) > 0:
        min_y, max_y = int(np.min(nz_y)), int(np.max(nz_y))
        min_x, max_x = int(np.min(nz_x)), int(np.max(nz_x))
        print(f"  Alpha content span: X=[{min_x}, {max_x}] (image width {w}), Y=[{min_y}, {max_y}] (image height {h})")
        print(f"  Bounds check: min_x>=0 ({min_x>=0}), max_x<w ({max_x<w}), min_y>=0 ({min_y>=0}), max_y<h ({max_y<h})")
        if min_x == 0 or max_x == w - 1 or min_y == 0 or max_y == h - 1:
            print(f"  WARNING: Content touches border! Left={min_x==0}, Right={max_x==w-1}, Top={min_y==0}, Bottom={max_y==h-1}")
