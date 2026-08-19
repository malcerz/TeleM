"""
Deep diagnostic of chart clipping on real 4K canvas (3840x2160) with default layout.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path("c:/_DEV/TeleM")))

import json
from PIL import Image, ImageDraw

from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay
from src.indicators.chart import _render_chart_indicator
from src.indicators.chart_utils import _build_chart_bg, generate_history_chart

root = Path("c:/_DEV/TeleM")
layout_path = root / "def_layout.json"
layout = normalize_layout(layout_path, 3840, 2160)

print("Layout loaded for 3840x2160:")
for k in ["fit_cadence_text", "fit_heart_rate_text"]:
    cfg = layout["indicators"].get(k)
    print(f"  {k}: {cfg}")

# Inspect chart raster generation directly
cad_cfg = layout["indicators"]["fit_cadence_text"]
hr_cfg = layout["indicators"]["fit_heart_rate_text"]

vals_cad = [60.0 + i % 30 for i in range(100)]
vals_hr = [120.0 + i % 40 for i in range(100)]

from src.indicators.helpers import s

size_cad = s(cad_cfg.get("size", 0.3), 3840)
size_hr = s(hr_cfg.get("size", 0.3), 3840)

# Render cadence chart
res_cad, rx, ry, _ = _render_chart_indicator(
    canvas_w=3840, canvas_h=2160, layout=layout,
    font_path="assets/Roboto-Bold.ttf",
    key="fit_cadence_text", value=75.0, unit="rpm", label="Cadence",
    cfg=cad_cfg, min_dim=2160, outline=2, fs=38,
    font=None, val_min=0, val_max=120, ticks=[], thickness=2,
    size_px=size_cad, ss=1,
    history_data=vals_cad, formatted_val="75 rpm", split_mode=True,
)

static_cad = res_cad.static
print(f"\nCadence static image size: {static_cad.size}, rx={rx}, ry={ry}")
static_cad.save("scratch/diag_cadence_static.png")

# Render HR chart
res_hr, rx_hr, ry_hr, _ = _render_chart_indicator(
    canvas_w=3840, canvas_h=2160, layout=layout,
    font_path="assets/Roboto-Bold.ttf",
    key="fit_heart_rate_text", value=145.0, unit="bpm", label="Heart Rate",
    cfg=hr_cfg, min_dim=2160, outline=2, fs=38,
    font=None, val_min=0, val_max=200, ticks=[], thickness=2,
    size_px=size_hr, ss=1,
    history_data=vals_hr, formatted_val="145 bpm", split_mode=True,
)

static_hr = res_hr.static
print(f"HR static image size: {static_hr.size}, rx_hr={rx_hr}, ry_hr={ry_hr}")
static_hr.save("scratch/diag_hr_static.png")

# Now compose full overlay to check final placement and bboxes
overlay = compose_overlay(
    canvas_w=3840, canvas_h=2160, layout=layout,
    font_path="assets/Roboto-Bold.ttf",
    date_text="2026-08-19", time_text="12:34:56",
    speed_value=32.5, distance_m=12345.0,
    indicator_values={"fit_cadence_text": 75.0, "fit_heart_rate_text": 145.0},
    chart_data={"fit_cadence_text": vals_cad, "fit_heart_rate_text": vals_hr},
    reuse_canvas=False,
)
overlay.save("scratch/diag_full_overlay.png")
print("Saved diagnostic images to scratch/")
