"""Inspect exact crop (21, 22, 76, 46) on exported frame."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/scratch/frame_30_etap8m3_post_fix.png")
c = img.crop((21, 22, 21 + 76, 22 + 46))
c.save("c:/_DEV/TeleM/scratch/crop_exact_time_block.png")
arr = np.asarray(c)

print(f"Exact time_block crop shape={arr.shape}")
print(f"min_RGB={arr.min(axis=(0,1))} max_RGB={arr.max(axis=(0,1))} mean_RGB={arr.mean(axis=(0,1)).astype(int)}")
dark_px = np.count_nonzero((arr[:, :, 0] < 40) & (arr[:, :, 1] < 40) & (arr[:, :, 2] < 40))
bright_px = np.count_nonzero((arr[:, :, 0] > 220) & (arr[:, :, 1] > 220) & (arr[:, :, 2] > 220))
print(f"dark_px={dark_px}, bright_px={bright_px}")
