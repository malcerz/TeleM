"""Examine extracted map crops for clipping or distortion."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
out_dir = root / "scratch" / "map_series"

def examine():
    for f in [0, 500, 1000, 2000, 3000, 4000, 5000]:
        p = out_dir / f"map_{f:04d}.png"
        if p.exists():
            img = Image.open(p)
            arr = np.array(img)
            # Check row-by-row variance/mean to detect if only a few rows have content (i.e. stripe)
            row_means = arr.mean(axis=(1, 2))
            row_stds = arr.std(axis=(1, 2))
            # Are there rows that are identical to the underlying video or flat?
            print(f"Frame {f:4d}: size={img.size}, top row mean={row_means[0]:.1f}, mid row mean={row_means[len(row_means)//2]:.1f}, bot row mean={row_means[-1]:.1f}")
            # Check if there is satellite imagery across all rows:
            print(f"   Row means min={row_means.min():.1f}, max={row_means.max():.1f}, std of row means={np.std(row_means):.1f}")

if __name__ == "__main__":
    examine()
