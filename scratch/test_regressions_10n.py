import sys
import json
from pathlib import Path
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.indicators.bar as bar_mod
from scratch.test_opt_slope_alt import _opt_render_slope, _opt_render_ruler

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    v10 = json.load(f)

print("=== 1. DISTANCE REGRESSION TEST ===")
dist_cfg = dict(v10["indicators"]["dist_visual"])
for val in [0.0, 1.0, 2.5, 5.0, 7.8, 10.0, None]:
    orig = bar_mod._render_ruler(
        canvas_w=1280, canvas_h=720, font_path="", value=val, unit="km", label="DISTANCE",
        cfg=dist_cfg, val_min=0.0, val_max=10.0, ticks=5, thickness=1, size_px=201, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    opt = _opt_render_ruler(
        canvas_w=1280, canvas_h=720, font_path="", value=val, unit="km", label="DISTANCE",
        cfg=dist_cfg, val_min=0.0, val_max=10.0, ticks=5, thickness=1, size_px=201, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    diff = ImageChops.difference(orig, opt)
    bbox = diff.getbbox()
    print(f"Dist val={val}: diff bbox = {bbox}")
    assert bbox is None, f"Distance parity failed for {val}"
print("DISTANCE REGRESSION: 100% BYTE EXACT PASS!")

print("\n=== 2. FONT SWITCHING TEST ===")
from src.indicators.helpers import resolve_indicator_font_path

for font_name in ["default", "Comic Sans", "Digital-7", "Iona-u1"]:
    f_path = resolve_indicator_font_path(font_name, "")
    orig_slope = bar_mod._render_slope(
        canvas_w=1280, canvas_h=720, font_path=f_path, value=3.5, unit="%", label="SLOPE",
        cfg=v10["indicators"]["slope_text"], val_min=-20.0, val_max=20.0, thickness=2, size_px=108, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    opt_slope = _opt_render_slope(
        canvas_w=1280, canvas_h=720, font_path=f_path, value=3.5, unit="%", label="SLOPE",
        cfg=v10["indicators"]["slope_text"], val_min=-20.0, val_max=20.0, thickness=2, size_px=108, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    diff = ImageChops.difference(orig_slope, opt_slope)
    bbox = diff.getbbox()
    print(f"Font '{font_name}' Slope diff bbox = {bbox}")
    assert bbox is None, f"Font parity failed for {font_name}"

    orig_alt = bar_mod._render_ruler(
        canvas_w=1280, canvas_h=720, font_path=f_path, value=345.0, unit="m", label="ALTITUDE",
        cfg=v10["indicators"]["alt_visual"], val_min=0.0, val_max=1000.0, ticks=5, thickness=1, size_px=115, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    opt_alt = _opt_render_ruler(
        canvas_w=1280, canvas_h=720, font_path=f_path, value=345.0, unit="m", label="ALTITUDE",
        cfg=v10["indicators"]["alt_visual"], val_min=0.0, val_max=1000.0, ticks=5, thickness=1, size_px=115, fs=9, outline=1, ss=1,
        formatted_val=None
    )
    diff_alt = ImageChops.difference(orig_alt, opt_alt)
    bbox_alt = diff_alt.getbbox()
    print(f"Font '{font_name}' Alt diff bbox = {bbox_alt}")
    assert bbox_alt is None, f"Font parity failed for {font_name} on Alt"

print("FONT SWITCHING: 100% BYTE EXACT PASS!")
