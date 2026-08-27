import math
import numpy as np
from PIL import Image

def test_rotation_math():
    w, h = 978, 978
    dst_w, dst_h = 691, 691
    angle_deg = 45.0
    angle_rad = math.radians(angle_deg)
    
    # Create test image with distinct quadrant colors and grid
    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            arr[y, x] = [x % 256, y % 256, (x + y) % 256, 255]
    img = Image.fromarray(arr, "RGBA")
    
    # Pillow rotate + crop
    rot_pil = img.rotate(angle_deg, resample=Image.BICUBIC, center=(w / 2.0, h / 2.0))
    crop_pil = rot_pil.crop((
        int(w / 2.0 - dst_w / 2.0),
        int(h / 2.0 - dst_h / 2.0),
        int(w / 2.0 - dst_w / 2.0) + dst_w,
        int(h / 2.0 - dst_h / 2.0) + dst_h,
    ))
    
    # Formula sampling (bicubic / bilinear)
    arr_pil = np.array(crop_pil)
    
    # Check 5 points
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    
    # In Pillow rotate, for an output pixel (out_x, out_y) in crop:
    # out_x ranges 0..dst_w-1, out_y ranges 0..dst_h-1
    # dst center relative coords:
    for test_pt in [(345, 345), (100, 100), (500, 200), (200, 500)]:
        tx, ty = test_pt
        dx = (tx + 0.5) - (dst_w * 0.5)
        dy = (ty + 0.5) - (dst_h * 0.5)
        
        # Counter-clockwise inverse transform
        src_x = (w * 0.5) + (cos_a * dx + sin_a * dy) - 0.5
        src_y = (h * 0.5) + (-sin_a * dx + cos_a * dy) - 0.5
        
        # Compare sampled pixel with Pillow
        p_val = arr_pil[ty, tx]
        print(f"Pt ({tx}, {ty}): Pillow RGBA={p_val[:3]}, Sample coords=({src_x:.2f}, {src_y:.2f})")

if __name__ == "__main__":
    test_rotation_math()
