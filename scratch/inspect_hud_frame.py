"""Inspect 01_python_hud_30.png directly."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/01_python_hud_30.png")
print(f"HUD image size: {img.size} mode: {img.mode}")

crops = {
    "time_block": (15, 15, 120, 80),
    "iso_text": (15, 290, 150, 325),
    "exposure_text": (15, 320, 120, 355),
    "temp_text": (15, 350, 140, 385),
    "solar_pct": (600, 50, 750, 80),
}

for name, bbox in crops.items():
    c = img.crop(bbox)
    alpha = np.asarray(c.getchannel("A"))
    print(f"[{name}] bbox={bbox} non-zero alpha pixels={np.count_nonzero(alpha)} max_alpha={alpha.max()}")
