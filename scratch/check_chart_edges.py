"""
Inspect alpha bounds and text clipping on chart static image.
"""
from PIL import Image
import numpy as np

for name in ["scratch/diag_cadence_static.png", "scratch/diag_hr_static.png"]:
    img = Image.open(name)
    arr = np.array(img)
    alpha = arr[:, :, 3]
    h, w = alpha.shape
    
    # Check non-zero alpha bounding box
    nz_y, nz_x = np.nonzero(alpha > 0)
    if len(nz_y) > 0:
        min_y, max_y = int(np.min(nz_y)), int(np.max(nz_y))
        min_x, max_x = int(np.min(nz_x)), int(np.max(nz_x))
        print(f"\n--- {name} (Image size: {w}x{h}) ---")
        print(f"  Content BBox: X=[{min_x}, {max_x}], Y=[{min_y}, {max_y}]")
        print(f"  Margin Left: {min_x} px, Margin Right: {w - 1 - max_x} px")
        print(f"  Margin Top: {min_y} px, Margin Bottom: {h - 1 - max_y} px")
        
        # Check if pixels touch edges (0 or w-1, h-1)
        touch_left = (min_x == 0)
        touch_right = (max_x == w - 1)
        touch_top = (min_y == 0)
        touch_bottom = (max_y == h - 1)
        print(f"  Touches border: Left={touch_left}, Right={touch_right}, Top={touch_top}, Bottom={touch_bottom}")
        
        # Check bottom row (are labels cut off?)
        print(f"  Bottom row alpha sum: {np.sum(alpha[h-1, :])}, second from bottom: {np.sum(alpha[h-2, :])}")
