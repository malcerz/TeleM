import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image
from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay
from scratch.test_regions_generation import get_layout_hud_regions_v2

layout = normalize_layout("def_layout.json", 1920, 1080)

img = compose_overlay(
    1920, 1080, layout, "",
    "2026-08-20", "12:34:56",
    28.5, 4500.0, 12000.0,
    145.0, 50.0, 300.0,
    100.0, 500.0, 25.0,
    indicator_values={
        "fit_cadence_text": 85.0,
        "fit_enhanced_speed_text": 28.5,
        "fit_heart_rate_text": 142.0,
        "fit_temperature_text": 24.5,
        "iso_text": 100.0,
        "exposure_text": 500.0,
        "temp_text": 25.0,
        "fit_battery_text": 85.0,
        "fit_battery_pct_text": 85.0,
        "fit_solar_pct_text": 45.0,
    },
    chart_data={"cadence": [(i, 70 + i%30) for i in range(100)], "heart_rate": [(i, 130 + i%20) for i in range(100)]},
    gps_track=[(52.0 + i*0.001, 21.0 + i*0.001) for i in range(100)],
    current_position=0.5,
)

arr_full = np.asarray(img)
alpha_full = arr_full[..., 3]
aw, ah, regs = get_layout_hud_regions_v2(layout, 1920, 1080, max_regions=3)

reconstructed = np.zeros((1080, 1920, 4), dtype=np.uint8)
atlas_img = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
for r in regs:
    dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
    crop = img.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
    atlas_img.paste(crop, (atlas_x, atlas_y))

for r in regs:
    dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
    crop_from_atlas = atlas_img.crop((atlas_x, atlas_y, atlas_x + rw, atlas_y + rh))
    reconstructed[dest_y:dest_y+rh, dest_x:dest_x+rw] = np.asarray(crop_from_atlas)

lost_alpha_mask = (alpha_full > 0) & (reconstructed[..., 3] == 0)
y_lost, x_lost = np.nonzero(lost_alpha_mask)
print(f"Lost pixels range: X=[{np.min(x_lost)}, {np.max(x_lost)}], Y=[{np.min(y_lost)}, {np.max(y_lost)}]")

# Find which indicators cover this range
for k, v in layout["indicators"].items():
    if v.get("enabled", True):
        lx, ly = v.get("x", 0.0), v.get("y", 0.0)
        px = int(round((lx / 100.0) * 1920)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * 1080)) if ly <= 100.0 else int(round(ly))
        print(f"  {k:25s}: pos=({px}, {py}) form={v.get('form')}")
