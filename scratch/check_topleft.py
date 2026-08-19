"""Find text pixels around (21, 22) on frame_30_etap8m3_720p.png."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/scratch/frame_30_etap8m3_720p.png")
c = img.crop((0, 0, 200, 150))
c.save("c:/_DEV/TeleM/scratch/crop_topleft_200x150.png")
arr = np.asarray(c)
print(f"Top-left 200x150 min={arr.min(axis=(0,1))} max={arr.max(axis=(0,1))} mean={arr.mean(axis=(0,1)).astype(int)}")

# Check if there is any black outline or white text (e.g. R < 50 or R > 250)
black_px = np.count_nonzero((arr[:, :, 0] < 40) & (arr[:, :, 1] < 40) & (arr[:, :, 2] < 40))
white_px = np.count_nonzero((arr[:, :, 0] > 230) & (arr[:, :, 1] > 230) & (arr[:, :, 2] > 230))
print(f"black outline pixels: {black_px}, white text pixels: {white_px}")
