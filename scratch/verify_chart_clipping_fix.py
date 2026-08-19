"""
Verification of Chart Label Clipping Bugfix for Cadence & Heart Rate in 4K & 1080p.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path("c:/_DEV/TeleM")))

from PIL import Image, ImageDraw
import numpy as np

from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay
from src.indicators.chart import _render_chart_indicator
from src.indicators.chart_utils import _build_chart_bg

root = Path("c:/_DEV/TeleM")
out_dir = root / "scratch" / "chart_clipping_verification"
out_dir.mkdir(parents=True, exist_ok=True)

layout_4k = normalize_layout(root / "def_layout.json", 3840, 2160)
layout_1080p = normalize_layout(root / "def_layout.json", 1920, 1080)

vals_cad = [55.0 + (i * 7) % 35 for i in range(100)]
vals_hr = [110.0 + (i * 9) % 55 for i in range(100)]

def test_clipping_bounds(img, name):
    arr = np.array(img)
    alpha = arr[:, :, 3]
    h, w = alpha.shape
    nz_y, nz_x = np.nonzero(alpha > 0)
    assert len(nz_y) > 0, f"Empty image for {name}"
    min_y, max_y = int(np.min(nz_y)), int(np.max(nz_y))
    min_x, max_x = int(np.min(nz_x)), int(np.max(nz_x))
    
    # Check edges
    left_ok = min_x > 0
    right_ok = max_x < w - 1
    top_ok = min_y > 0
    bottom_ok = max_y < h - 1
    
    print(f"[{name}] Size: {w}x{h}")
    print(f"  X span: [{min_x}, {max_x}] (margin left={min_x}px, right={w-1-max_x}px) -> {'PASS' if (left_ok and right_ok) else 'FAIL'}")
    print(f"  Y span: [{min_y}, {max_y}] (margin top={min_y}px, bottom={h-1-max_y}px) -> {'PASS' if (top_ok and bottom_ok) else 'FAIL'}")
    
    return left_ok and right_ok and top_ok and bottom_ok

print("===============================================================================")
print("1. 4K STATIC CHART RASTER BOUNDS VERIFICATION")
print("===============================================================================")

from src.indicators.helpers import s

# 4K Cadence
size_4k_cad = s(layout_4k["indicators"]["fit_cadence_text"].get("size", 0.3), 3840)
res_cad_4k, rx, ry, _ = _render_chart_indicator(
    canvas_w=3840, canvas_h=2160, layout=layout_4k,
    font_path="assets/Roboto-Bold.ttf",
    key="fit_cadence_text", value=64.0, unit="rpm", label="Cadence",
    cfg=layout_4k["indicators"]["fit_cadence_text"], min_dim=2160, outline=2, fs=38,
    font=None, val_min=0, val_max=87, ticks=[], thickness=2,
    size_px=size_4k_cad, ss=1,
    history_data=vals_cad, formatted_val="64 rpm", split_mode=True,
)
cad_4k_img = res_cad_4k.static
cad_4k_img.save(out_dir / "cadence_4k_static.png")
cad_4k_pass = test_clipping_bounds(cad_4k_img, "Cadence 4K Static")

# 4K Heart Rate
size_4k_hr = s(layout_4k["indicators"]["fit_heart_rate_text"].get("size", 0.3), 3840)
res_hr_4k, rx_hr, ry_hr, _ = _render_chart_indicator(
    canvas_w=3840, canvas_h=2160, layout=layout_4k,
    font_path="assets/Roboto-Bold.ttf",
    key="fit_heart_rate_text", value=145.0, unit="bpm", label="Heart Rate",
    cfg=layout_4k["indicators"]["fit_heart_rate_text"], min_dim=2160, outline=2, fs=38,
    font=None, val_min=77, val_max=116, ticks=[], thickness=2,
    size_px=size_4k_hr, ss=1,
    history_data=vals_hr, formatted_val="145 bpm", split_mode=True,
)
hr_4k_img = res_hr_4k.static
hr_4k_img.save(out_dir / "hr_4k_static.png")
hr_4k_pass = test_clipping_bounds(hr_4k_img, "Heart Rate 4K Static")

print("\n===============================================================================")
print("2. 1080P STATIC CHART RASTER BOUNDS VERIFICATION")
print("===============================================================================")

# 1080p Cadence
size_1080_cad = s(layout_1080p["indicators"]["fit_cadence_text"].get("size", 0.3), 1920)
res_cad_1080, rx1, ry1, _ = _render_chart_indicator(
    canvas_w=1920, canvas_h=1080, layout=layout_1080p,
    font_path="assets/Roboto-Bold.ttf",
    key="fit_cadence_text", value=64.0, unit="rpm", label="Cadence",
    cfg=layout_1080p["indicators"]["fit_cadence_text"], min_dim=1080, outline=1, fs=19,
    font=None, val_min=0, val_max=87, ticks=[], thickness=1,
    size_px=size_1080_cad, ss=1,
    history_data=vals_cad, formatted_val="64 rpm", split_mode=True,
)
cad_1080_img = res_cad_1080.static
cad_1080_img.save(out_dir / "cadence_1080p_static.png")
cad_1080_pass = test_clipping_bounds(cad_1080_img, "Cadence 1080p Static")

# 1080p Heart Rate
size_1080_hr = s(layout_1080p["indicators"]["fit_heart_rate_text"].get("size", 0.3), 1920)
res_hr_1080, rx2, ry2, _ = _render_chart_indicator(
    canvas_w=1920, canvas_h=1080, layout=layout_1080p,
    font_path="assets/Roboto-Bold.ttf",
    key="fit_heart_rate_text", value=145.0, unit="bpm", label="Heart Rate",
    cfg=layout_1080p["indicators"]["fit_heart_rate_text"], min_dim=1080, outline=1, fs=19,
    font=None, val_min=77, val_max=116, ticks=[], thickness=1,
    size_px=size_1080_hr, ss=1,
    history_data=vals_hr, formatted_val="145 bpm", split_mode=True,
)
hr_1080_img = res_hr_1080.static
hr_1080_img.save(out_dir / "hr_1080p_static.png")
hr_1080_pass = test_clipping_bounds(hr_1080_img, "Heart Rate 1080p Static")

print("\n===============================================================================")
print("3. FULL 4K COMPOSITE OVERLAY VERIFICATION")
print("===============================================================================")

overlay_4k = compose_overlay(
    canvas_w=3840, canvas_h=2160, layout=layout_4k,
    font_path="assets/Roboto-Bold.ttf",
    date_text="2026-08-19", time_text="12:34:56",
    speed_value=32.5, distance_m=12345.0,
    indicator_values={"fit_cadence_text": 64.0, "fit_heart_rate_text": 145.0},
    chart_data={"fit_cadence_text": vals_cad, "fit_heart_rate_text": vals_hr},
    reuse_canvas=False,
)
overlay_4k.save(out_dir / "full_overlay_4k.png")

# Crop Cadence region from full overlay
cad_cfg = layout_4k["indicators"]["fit_cadence_text"]
cx = int(round(3840 * cad_cfg["x"] / 100.0))
cy = int(round(2160 * cad_cfg["y"] / 100.0))
cw = cad_4k_img.width
ch = cad_4k_img.height
cad_crop = overlay_4k.crop((cx - cw // 2 - 10, cy - ch // 2 - 10, cx + cw // 2 + 10, cy + ch // 2 + 10))
cad_crop.save(out_dir / "cadence_4k_final_crop.png")

# Crop HR region from full overlay
hr_cfg = layout_4k["indicators"]["fit_heart_rate_text"]
hx = int(round(3840 * hr_cfg["x"] / 100.0))
hy = int(round(2160 * hr_cfg["y"] / 100.0))
hw = hr_4k_img.width
hh = hr_4k_img.height
hr_crop = overlay_4k.crop((hx - hw // 2 - 10, hy - hh // 2 - 10, hx + hw // 2 + 10, hy + hh // 2 + 10))
hr_crop.save(out_dir / "hr_4k_final_crop.png")

print("Saved all verification artifacts to scratch/chart_clipping_verification/")
assert cad_4k_pass and hr_4k_pass and cad_1080_pass and hr_1080_pass, "Some bounds failed!"
print("\nALL CLIPPING BOUND CHECKS: PASS!")
