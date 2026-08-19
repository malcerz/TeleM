"""Analyze pixel regions for time_block, ISO, Exposure, Temp in exported frame."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/scratch/frame_30_etap8m3_720p.png")
print(f"Exported Frame size: {img.size}")

crops = {
    "time_block": (15, 15, 120, 80),
    "iso_text": (15, 290, 150, 325),
    "exposure_text": (15, 320, 120, 355),
    "temp_text": (15, 350, 140, 385),
    "solar_pct": (600, 50, 750, 80),
    "map": (1000, 30, 1260, 290),
}

for name, bbox in crops.items():
    c = img.crop(bbox)
    c.save(f"c:/_DEV/TeleM/scratch/crop_720p_{name}.png")
    arr = np.asarray(c)
    print(f"[{name}] bbox={bbox} mean_RGB={arr.mean(axis=(0,1)).astype(int)} min_RGB={arr.min(axis=(0,1))} max_RGB={arr.max(axis=(0,1))}")
