import os
import numpy as np
from PIL import Image

for name in ["01_python_hud.png", "02_buffer_sent_to_dll.png", "03_d3d11_hud_texture.png", "04_videoprocessor_output.png", "05_final_encoded_frame.png"]:
    if os.path.exists(name):
        im = Image.open(name)
        arr = np.array(im)
        print(f"=== IMAGE {name} ===")
        print(f"  Shape: {arr.shape}, Dtype: {arr.dtype}")
        non_zero = (arr > 20).sum()
        print(f"  Min: {arr.min()}, Max: {arr.max()}, Mean: {arr.mean():.2f}, Non-black (>20) count: {non_zero}")
        if arr.ndim == 3 and arr.shape[2] >= 3:
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            print(f"  Channel Means -> R: {r.mean():.2f}, G: {g.mean():.2f}, B: {b.mean():.2f}")
            print(f"  Channel Max   -> R: {r.max()}, G: {g.max()}, B: {b.max()}")
