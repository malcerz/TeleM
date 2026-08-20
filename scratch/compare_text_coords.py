import numpy as np
from PIL import Image

im_a = Image.open('scratch/exact_atlas_0.0.png')
im_f = Image.open('scratch/exact_full_0.0.png')

# Find position of black stroke / white text of time block (top left 0..500x0..500)
# Substract base video frame without HUD
base = Image.open('scratch/frame_bbox_0.0.png') # or read from base video
# Let's inspect coordinates of white pixels (R>240, G>240, B>240) in time_block area (X: 0..800, Y: 0..300)
arr_a = np.asarray(im_a)[0:300, 0:800]
arr_f = np.asarray(im_f)[0:300, 0:800]

white_a = (arr_a[..., 0] > 240) & (arr_a[..., 1] > 240) & (arr_a[..., 2] > 240)
white_f = (arr_f[..., 0] > 240) & (arr_f[..., 1] > 240) & (arr_f[..., 2] > 240)

ya, xa = np.nonzero(white_a)
yf, xf = np.nonzero(white_f)

print(f"Time block white text bbox in Atlas: X=[{np.min(xa)}, {np.max(xa)}], Y=[{np.min(ya)}, {np.max(ya)}]")
print(f"Time block white text bbox in Full:  X=[{np.min(xf)}, {np.max(xf)}], Y=[{np.min(yf)}, {np.max(yf)}]")
