"""Verify extracted map crops across 4K, 1080p, and 720p."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
out_dir = root / "scratch" / "validation_exports"

def verify():
    for label, exp_size in [("4k", (691, 691)), ("1080p", (346, 346)), ("720p", (230, 230))]:
        p = out_dir / f"map_crop_30_{label}.png"
        assert p.exists(), f"Missing {p}"
        img = Image.open(p)
        arr = np.array(img)
        print(f"[{label.upper()}] Size: {img.size} (expected {exp_size})")
        print(f"  Pixel stats: min={arr.min()}, max={arr.max()}, mean={arr.mean():.2f}, std={arr.std():.2f}")
        # Verify non-empty and non-stripe
        row_means = arr.mean(axis=(1, 2))
        col_means = arr.mean(axis=(0, 2))
        print(f"  Row means min={row_means.min():.1f}, max={row_means.max():.1f}")
        print(f"  Col means min={col_means.min():.1f}, max={col_means.max():.1f}")
        # Is the entire area populated with map content?
        assert img.size == exp_size, f"Size mismatch: {img.size} != {exp_size}"
        assert arr.mean() > 40.0, f"Map appears blank/empty: mean={arr.mean()}"
        print(f"  -> MAP VALIDATION: PASS")

if __name__ == "__main__":
    verify()
