"""Print ASCII representation of text in crop_topleft_200x150.png."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/scratch/crop_topleft_200x150.png")
arr = np.asarray(img)
# Sky is blueish: R ~ 210, G ~ 227, B ~ 254 (R < 100 is outline, R > 240 is text)
mask = (arr[:, :, 0] < 50) | ((arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240))

for y in range(0, 150, 4):
    line = "".join("#" if mask[y, x] else "." for x in range(0, 120, 2))
    if "#" in line:
        print(f"y={y:3d}: {line}")
