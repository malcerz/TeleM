"""Generate all validation artifacts and screenshots for ETAP 8M.5 report."""
import sys
import os
import json
import subprocess
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.dispatcher import render_value_indicator
from src.indicators.gauge import _render_gauge_indicator, _gauge_ticks
from src.indicators.compositor import compose_overlay
from src.gui.layout_manager import normalize_layout
from src.indicators.helpers import s

out_dir = root / "Raporty" / "etap8m5_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

font_path = "assets/Roboto-Bold.ttf"

# Base gauge config
cfg_default = {
    "enabled": True, "label": "Enhanced Speed", "x": 50.0, "y": 80.0, "rotation": 0,
    "form": "gauge", "font_size": 2.4, "size": 12.5, "thickness": 1,
    "min_val": 0.0, "max_val": 40.0, "ticks": 10, "source": "fit",
    "show_marker": True, "marker_size": 5, "marker_color": "#ff0000",
    "show_units": True, "show_value": True, "decimals": 1,
}

print("=" * 70)
print("1. Generating Multi-Resolution Validation Artifacts (4K, 1080p, 720p, 480p)")
print("=" * 70)

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

for w, h, res_name in resolutions:
    layout = {"global": {}, "indicators": {"gauge": dict(cfg_default)}}
    img, rx, ry, _ = render_value_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="gauge", value=16.17, unit="km/h", label="Speed",
        cfg_override=cfg_default,
    )
    img.save(out_dir / f"gauge_res_{res_name}.png")
    arr = np.array(img)
    alpha = arr[:, :, 3]
    print(f"[{res_name} ({w}x{h})] image size={img.size}, non_zero_alpha={np.count_nonzero(alpha > 0)}")

print("\n" + "=" * 70)
print("2. Generating Multi-Value Test Artifacts (0, 10, 20, 30, 40, 16.17)")
print("=" * 70)

test_values = [0.0, 10.0, 20.0, 30.0, 40.0, 16.17]
for val in test_values:
    layout = {"global": {}, "indicators": {"gauge": dict(cfg_default)}}
    img, rx, ry, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path=font_path,
        key="gauge", value=val, unit="km/h", label="Speed",
        cfg_override=cfg_default,
        formatted_val=f"{val:.1f} km/h",
    )
    img.save(out_dir / f"gauge_val_{val:.2f}.png")
    print(f"Value: {val:6.2f} -> saved gauge_val_{val:.2f}.png")

print("\n" + "=" * 70)
print("3. Generating Ticks Property Variations (Tick=4, Tick=10, Tick=20)")
print("=" * 70)

for tick_cnt in [4, 10, 20]:
    cfg_var = dict(cfg_default)
    cfg_var["ticks"] = tick_cnt
    layout = {"global": {}, "indicators": {"gauge": cfg_var}}
    img, rx, ry, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path=font_path,
        key="gauge", value=22.5, unit="km/h", label="Speed",
        cfg_override=cfg_var,
    )
    img.save(out_dir / f"preview_tick_{tick_cnt}.png")
    arr = np.array(img)
    print(f"Ticks: {tick_cnt:2d} -> non_zero_alpha={np.count_nonzero(arr[:, :, 3] > 0)}")

print("\n" + "=" * 70)
print("4. Generating Width Property Variations (Width=1, Width=5, Width=10)")
print("=" * 70)

for width_val in [1, 5, 10]:
    cfg_var = dict(cfg_default)
    cfg_var["thickness"] = width_val
    layout = {"global": {}, "indicators": {"gauge": cfg_var}}
    img, rx, ry, _ = render_value_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path=font_path,
        key="gauge", value=22.5, unit="km/h", label="Speed",
        cfg_override=cfg_var,
    )
    img.save(out_dir / f"preview_width_{width_val}.png")
    arr = np.array(img)
    print(f"Width (thickness): {width_val:2d} -> non_zero_alpha={np.count_nonzero(arr[:, :, 3] > 0)}")

print("\nAll artifact images generated successfully in Raporty/etap8m5_artifacts/.")
