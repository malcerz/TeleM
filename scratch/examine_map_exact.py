"""Examine the exact map region pixels in map_region_exact.png."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
p = root / "scratch" / "gui_export_inspection" / "map_region_exact.png"

def examine():
    img = Image.open(p)
    arr = np.array(img)
    print(f"Map region exact size: {img.size}")
    
    # Check if there is an actual map or if it's mostly background video
    # In satellite map style with red route:
    # Let's check color distribution across rows:
    row_means = arr.mean(axis=(1, 2))
    print(f"Row means: min={row_means.min():.1f}, max={row_means.max():.1f}, overall={row_means.mean():.1f}")
    
    # Check if there is a distinct border or box
    # What does the map look like in the GUI preview?
    # Let's render the GUI preview of this frame at logical size (960x540) to compare!

if __name__ == "__main__":
    examine()
