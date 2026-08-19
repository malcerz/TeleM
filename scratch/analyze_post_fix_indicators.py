"""Analyze pixel regions for all indicators on post-fix exported frame."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/scratch/frame_30_etap8m3_post_fix.png")
print(f"Exported Frame size: {img.size}")

crops = {
    "time_block": (15, 15, 120, 80),
    "iso_text": (15, 290, 150, 325),
    "exposure_text": (15, 320, 120, 355),
    "temp_text": (15, 350, 140, 385),
    "solar_pct": (600, 50, 750, 80),
    "battery_pct": (1180, 50, 1270, 80),
    "track_map": (1000, 30, 1260, 290),
    "gauge": (515, 544, 731, 715),
}

for name, bbox in crops.items():
    c = img.crop(bbox)
    c.save(f"c:/_DEV/TeleM/scratch/crop_post_fix_{name}.png")
    arr = np.asarray(c)
    # Count black text outline (R,G,B < 30) and bright white/colored text (R,G,B > 220)
    dark_px = np.count_nonzero((arr[:, :, 0] < 40) & (arr[:, :, 1] < 40) & (arr[:, :, 2] < 40))
    bright_px = np.count_nonzero((arr[:, :, 0] > 220) & (arr[:, :, 1] > 220) & (arr[:, :, 2] > 220))
    print(f"[{name:15s}] bbox={bbox} dark_px={dark_px:4d} bright_px={bright_px:4d} min_RGB={arr.min(axis=(0,1))} max_RGB={arr.max(axis=(0,1))}")
