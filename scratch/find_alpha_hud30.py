"""Find all non-zero alpha pixels in 01_python_hud_30.png."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/01_python_hud_30.png")
arr = np.asarray(img)
alpha = arr[:, :, 3]
ys, xs = np.where(alpha > 0)
print(f"01_python_hud_30.png total non-zero alpha={len(xs)}")
if len(xs) > 0:
    print(f"X range: [{xs.min()}, {xs.max()}], Y range: [{ys.min()}, {ys.max()}]")
