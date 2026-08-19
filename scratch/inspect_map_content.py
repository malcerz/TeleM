"""Inspect what is inside cpu_working_map.png."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
p = root / "scratch" / "gui_export_inspection" / "cpu_working_map.png"

def inspect():
    img = Image.open(p)
    arr = np.array(img)
    print(f"Image size: {img.size}")
    
    # Are the pixels satellite imagery or something else?
    # Let's save a full brightness boosted version to see what is on it
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    
    # Check if there is satellite imagery across all (0..691, 0..691)
    print(f"Alpha min={alpha.min()}, max={alpha.max()}, mean={alpha.mean():.2f}")
    print(f"RGB mean R={rgb[:,:,0].mean():.1f}, G={rgb[:,:,1].mean():.1f}, B={rgb[:,:,2].mean():.1f}")
    
    # Check if the map is dark satellite imagery of fields/roads
    # If the user looked at the 4K video on a dark background or high contrast,
    # the satellite imagery has dark green/brown forest and an orange/red track line passing horizontally.
    # What did the GUI preview look like? Let's check!

if __name__ == "__main__":
    inspect()
