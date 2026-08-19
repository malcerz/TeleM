"""Inspect crop of dump_composed_img_30.png."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/scratch/dump_composed_img_30.png")
c = img.crop((21, 22, 21 + 76, 22 + 46))
arr = np.asarray(c)
print(f"dump_composed_img_30 time_block alpha non-zero={np.count_nonzero(arr[:,:,3])} max_alpha={arr[:,:,3].max()}")
print(f"min_RGBA={arr.min(axis=(0,1))} max_RGBA={arr.max(axis=(0,1))}")
