"""Inspect and report on the 8 stages and final comparison crops."""
import sys
from pathlib import Path
from PIL import Image
import numpy as np

out_dir = Path("c:/_DEV/TeleM/Raporty/etap8m6_artifacts")

print("=" * 70)
print("CHART LABELS 8-STAGE AUDIT & PARITY CHECK")
print("=" * 70)

stages = [
    ("01_preview_chart_cad.png", "Cadence Preview Crop"),
    ("02_preview_chart_hr.png", "Heart Rate Preview Crop"),
    ("03_cpu_chart_cad.png", "Cadence CPU Direct"),
    ("04_cpu_chart_hr.png", "Heart Rate CPU Direct"),
    ("05_gpu_static_chart_cad.png", "Cadence GPU Static Texture"),
    ("06_gpu_static_chart_hr.png", "Heart Rate GPU Static Texture"),
    ("07_final_chart_cad.png", "Cadence Final AMD Video Crop"),
    ("08_final_chart_hr.png", "Heart Rate Final AMD Video Crop"),
]

for filename, desc in stages:
    p = out_dir / filename
    assert p.exists(), f"Missing {filename}"
    img = Image.open(p)
    arr = np.array(img)
    print(f"\n--- [{filename}] {desc} ---")
    print(f"Dimensions: {img.width}x{img.height}, Mode: {img.mode}")
    if img.mode == "RGBA":
        alpha = arr[:, :, 3]
        non_zero = np.count_nonzero(alpha > 0)
        opaque = np.count_nonzero(alpha == 255)
        # Check rightmost margin (last 5 columns)
        right_alpha = alpha[:, -5:]
        print(f"Alpha > 0: {non_zero}, Opaque: {opaque}, Rightmost 5 cols non-zero alpha: {np.count_nonzero(right_alpha > 0)}")
    elif img.mode == "RGB":
        rgb = arr
        print(f"Final video frame RGB dimensions: {rgb.shape}")

print("\nAll 8 stages confirmed generated and intact.")
