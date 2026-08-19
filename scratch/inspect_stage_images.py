"""Inspect images 01 to 04 in etap8m5_artifacts."""
from PIL import Image
import numpy as np
from pathlib import Path

out_dir = Path("c:/_DEV/TeleM/Raporty/etap8m5_artifacts")

for img_name in ["01_preview_gauge.png", "02_cpu_gauge_raw.png", "03_gpu_capture_source.png", "04_gpu_uploaded_texture.png"]:
    p = out_dir / img_name
    if not p.exists():
        continue
    img = Image.open(p)
    arr = np.array(img)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]
    non_zero = np.count_nonzero(alpha > 0)
    print(f"--- {img_name} ---")
    print(f"Size: {img.size}, Mode: {img.mode}, non-zero alpha: {non_zero}")
    # Let's check max alpha, mean RGB
    print(f"Alpha min: {alpha.min()}, max: {alpha.max()}, unique alpha values count: {len(np.unique(alpha))}")
    # Where are the pixels located in Y?
    y_indices, x_indices = np.where(alpha > 0)
    if len(y_indices) > 0:
        print(f"Bounding box of alpha>0: x=[{x_indices.min()}..{x_indices.max()}], y=[{y_indices.min()}..{y_indices.max()}]")
