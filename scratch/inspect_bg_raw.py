"""
Detailed inspection of _build_chart_bg geometry, fonts, margins and text coordinates.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path("c:/_DEV/TeleM")))

from PIL import Image, ImageDraw
import numpy as np
from src.indicators.chart_utils import _build_chart_bg
from src.gui.layout_manager import normalize_layout
from src.indicators.helpers import s

root = Path("c:/_DEV/TeleM")
layout = normalize_layout(root / "def_layout.json", 3840, 2160)
cad_cfg = layout["indicators"]["fit_cadence_text"]

chart_w = int(s(cad_cfg.get("size", 0.3), 3840))
chart_h = max(40, int(chart_w * 0.4))
vals_cad = [60.0 + i % 30 for i in range(100)]

bg_img, points, plot_y1, plot_y2, calc_thickness = _build_chart_bg(
    history_values=vals_cad,
    width=chart_w,
    height=chart_h,
    line_color=(255, 255, 0),
    line_thickness=1,
    fill_alpha=200,
    fill_color=(255, 255, 127),
    show_axes=True,
    grid_color=(68, 68, 68, 60),
    time_labels=None,
    value_labels=None,
    supersample=1,
    custom_min_val=0.0,
    custom_max_val=87.0,
    label_count=2,
    label_units=False,
    unit="",
    show_average=False,
    label_font_size=0,
    font_path="assets/Roboto-Bold.ttf",
)

bg_img.save("scratch/diag_bg_raw.png")
arr = np.array(bg_img)
alpha = arr[:, :, 3]
h, w = alpha.shape
print(f"bg_img size: {w}x{h}")
print(f"plot_y1: {plot_y1}, plot_y2: {plot_y2}")

# Let's inspect where X labels and Y labels were drawn
print(f"Bottom row of bg_img with alpha: {np.max(np.nonzero(alpha > 0)[0])} vs height {h}")
print(f"Top row of bg_img with alpha: {np.min(np.nonzero(alpha > 0)[0])}")
print(f"Left col of bg_img with alpha: {np.min(np.nonzero(alpha > 0)[1])}")
print(f"Right col of bg_img with alpha: {np.max(np.nonzero(alpha > 0)[1])}")
