"""Analyze the extracted crop images and examine map geometry and text."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
out_dir = root / "scratch" / "gui_export_inspection"

def check_crops():
    for f in [30, 225, 450, 1000, 2500, 5000]:
        map_p = out_dir / f"map_crop_{f:04d}.png"
        bat_p = out_dir / f"bat_crop_{f:04d}.png"
        sol_p = out_dir / f"solar_crop_{f:04d}.png"
        
        print(f"\n--- FRAME {f:04d} ---")
        if map_p.exists():
            img = Image.open(map_p)
            arr = np.array(img)
            # Find non-black/non-transparent pixels
            print(f"Map crop {map_p.name}: size={img.size}, min={arr.min()}, max={arr.max()}")
        if bat_p.exists():
            img = Image.open(bat_p)
            print(f"Battery crop {bat_p.name}: size={img.size}")
        if sol_p.exists():
            img = Image.open(sol_p)
            print(f"Solar crop {sol_p.name}: size={img.size}")

if __name__ == "__main__":
    check_crops()
