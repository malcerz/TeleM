import json
import sys
from pathlib import Path
from PIL import Image
import numpy as np

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.indicators.bar import _render_bar_indicator
from src.indicators.dispatcher import render_value_indicator

layout = json.load(open("def_layout.json"))
w, h = 3840, 2160

# 1. Direct render of fit_distance_text (Horizontal bar)
dist_cfg = layout["indicators"]["fit_distance_text"]
print("fit_distance_text config:", dist_cfg)

res_dist, rx_dist, ry_dist, _ = render_value_indicator(
    canvas_w=w, canvas_h=h, layout=layout, font_path="arial.ttf",
    key="fit_distance_text", value=12.345, unit=dist_cfg.get("unit", "km"),
    label=dist_cfg.get("label", "Dystans"),
)
print(f"Direct render dist: size={res_dist.size if res_dist else None}, pos=({rx_dist}, {ry_dist})")
if res_dist:
    res_dist.save("scratch/debug_dist_bar_direct.png")

# 2. Direct render of alt_text (Vertical bar)
alt_cfg = layout["indicators"]["alt_text"]
print("alt_text config:", alt_cfg)

res_alt, rx_alt, ry_alt, _ = render_value_indicator(
    canvas_w=w, canvas_h=h, layout=layout, font_path="arial.ttf",
    key="alt_text", value=350.0, unit=alt_cfg.get("unit", "m"),
    label=alt_cfg.get("label", "Wysokość"),
)
print(f"Direct render alt: size={res_alt.size if res_alt else None}, pos=({rx_alt}, {ry_alt})")
if res_alt:
    res_alt.save("scratch/debug_alt_bar_direct.png")

# 3. Check what was in debug_ref_fit_distance_text.png and debug_above_fit_distance_text.png
ref_bar = Image.open("scratch/debug_ref_fit_distance_text.png")
above_bar = Image.open("scratch/debug_above_fit_distance_text.png")
diff_bar = np.max(np.abs(np.array(ref_bar).astype(int) - np.array(above_bar).astype(int)))
print(f"Diff between ref_bar and above_bar: {diff_bar}")

# 4. Check why BAR in amd_frame_150.png had difference
# Let's inspect the actual pixels of crop_bar_amd.png vs crop_bar_ref.png
crop_bar_amd = Image.open("scratch/crop_bar_amd.png")
crop_bar_ref = Image.open("scratch/crop_bar_ref.png")
# Save visual diff
diff_img = Image.fromarray(np.uint8(np.abs(np.array(crop_bar_amd.convert('RGB')) - np.array(crop_bar_ref.convert('RGB')))))
diff_img.save("scratch/debug_bar_diff_visual.png")
print("Saved scratch/debug_bar_diff_visual.png")
