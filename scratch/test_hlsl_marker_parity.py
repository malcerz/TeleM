import math
import numpy as np
from PIL import Image, ImageDraw

def test_marker_parity():
    size = 634
    r = 28 # 7 * 4
    c = size / 2.0
    
    # 1. Pillow Reference
    img_pil = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img_pil)
    tip = (c, c - r * 1.8)
    left = (c - r * 0.65, c + r * 0.75)
    right = (c + r * 0.65, c + r * 0.75)
    d.polygon((tip, left, right), fill=(255, 255, 255, 255), outline=(0, 0, 0, 220))
    
    arr_pil = np.array(img_pil)
    
    # Check bounding box of marker
    non_zero = np.where(arr_pil[:, :, 3] > 0)
    y_min, y_max = np.min(non_zero[0]), np.max(non_zero[0])
    x_min, x_max = np.min(non_zero[1]), np.max(non_zero[1])
    print(f"Marker bbox in {size}x{size}: X=[{x_min}..{x_max}], Y=[{y_min}..{y_max}] (width={x_max-x_min+1}, height={y_max-y_min+1})")
    
    # Crop the static marker tile
    marker_tile = img_pil.crop((x_min, y_min, x_max + 1, y_max + 1))
    print(f"Marker tile size: {marker_tile.size}")
    
    # If we paste this static marker tile at (x_min, y_min):
    img_test = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img_test.paste(marker_tile, (x_min, y_min))
    arr_test = np.array(img_test)
    
    diff = np.max(np.abs(arr_pil.astype(int) - arr_test.astype(int)))
    print(f"Static marker paste max diff: {diff} (0 = exact 100% bit-for-bit parity!)")

if __name__ == "__main__":
    test_marker_parity()
