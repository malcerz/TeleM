"""Find exact bbox of text in crop_topleft_200x150.png."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/scratch/crop_topleft_200x150.png")
arr = np.asarray(img)
# Sky is blueish: R ~ 210, G ~ 227, B ~ 254 (R < 100 is outline, R > 245 and G > 245 is text)
mask = (arr[:, :, 0] < 50) | ((arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240))
ys, xs = np.where(mask)
if len(xs) > 0:
    print(f"Text detected at x: [{xs.min()}, {xs.max()}], y: [{ys.min()}, {ys.max()}] -> bbox=({xs.min()}, {ys.min()}, {xs.max()-xs.min()+1}, {ys.max()-ys.min()+1})")
else:
    print("No text detected")
