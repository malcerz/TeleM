"""Inspect full map crops from real AMD GPU exports."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")

def inspect_map_crops():
    for label in ["4k", "1080p", "720p"]:
        p = root / "scratch" / "validation_exports" / f"map_crop_30_{label}.png"
        img = Image.open(p)
        arr = np.array(img)
        w, h = img.size
        print(f"\n[{label.upper()} MAP CROP]")
        print(f"  Size: {w}x{h}")
        # Sample 4 corners and center:
        tl = arr[h//8, w//8]
        tr = arr[h//8, 7*w//8]
        bl = arr[7*h//8, w//8]
        br = arr[7*h//8, 7*w//8]
        center = arr[h//2, w//2]
        print(f"  Top-Left (12%, 12%):    RGB={tl[:3]}")
        print(f"  Top-Right (12%, 88%):   RGB={tr[:3]}")
        print(f"  Bottom-Left (88%, 12%): RGB={bl[:3]}")
        print(f"  Bottom-Right (88%, 88%):RGB={br[:3]}")
        print(f"  Center:                 RGB={center[:3]}")
        # Standard deviation of rows and columns
        row_std = np.std(arr.mean(axis=(1, 2)))
        col_std = np.std(arr.mean(axis=(0, 2)))
        print(f"  Row Mean Std: {row_std:.2f}, Col Mean Std: {col_std:.2f}")

if __name__ == "__main__":
    inspect_map_crops()
