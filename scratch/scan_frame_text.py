"""Scan the entire frame_30_etap8m3_post_fix.png to find all text regions."""
from PIL import Image
import numpy as np

img = Image.open("c:/_DEV/TeleM/scratch/frame_30_etap8m3_post_fix.png")
arr = np.asarray(img)
w, h = img.size

# Look for dark text outline (R,G,B < 30) or pure white text (R,G,B > 240)
dark_mask = (arr[:, :, 0] < 30) & (arr[:, :, 1] < 30) & (arr[:, :, 2] < 30)
bright_mask = (arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240)
text_mask = dark_mask | bright_mask

# Divide screen into 100x100 blocks and count text pixels
for y in range(0, h, 60):
    for x in range(0, w, 100):
        block = text_mask[y:min(h, y+60), x:min(w, x+100)]
        cnt = np.count_nonzero(block)
        if cnt > 20:
            print(f"Block ({x:4d}, {y:4d}, 100, 60): {cnt:4d} text pixels")
