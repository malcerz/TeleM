"""Verify pixel parity and elements across all 5 gauge stages."""
import sys
from pathlib import Path
from PIL import Image
import numpy as np

out_dir = Path("c:/_DEV/TeleM/Raporty/etap8m5_artifacts")

print("=" * 70)
print("GAUGE 5-STAGE COMPARISON & PARITY AUDIT")
print("=" * 70)

stages = [
    ("01_preview_gauge.png", "Preview Gauge Crop (CPU HUD)"),
    ("02_cpu_gauge_raw.png", "CPU Gauge Raw (Direct Renderer)"),
    ("03_gpu_capture_source.png", "GPU Capture Source (Compositor Capture)"),
    ("04_gpu_uploaded_texture.png", "GPU Uploaded Texture (Pre-D3D11 Upload)"),
    ("05_final_gauge_crop.png", "Final AMD MP4 Video Frame (D3D11+AMF Native)"),
]

for filename, desc in stages:
    p = out_dir / filename
    if not p.exists():
        print(f"MISSING: {filename}")
        continue
    img = Image.open(p)
    arr = np.array(img)
    print(f"\n--- [{filename}] {desc} ---")
    print(f"Dimensions: {img.width}x{img.height}, Mode: {img.mode}")

    if img.mode == "RGBA":
        alpha = arr[:, :, 3]
        rgb = arr[:, :, :3]
        non_zero = np.count_nonzero(alpha > 0)
        opaque = np.count_nonzero(alpha == 255)
        # White ticks / labels (R > 180, G > 180, B > 180, A > 100)
        white_px = np.count_nonzero((alpha > 100) & (rgb[:, :, 0] > 180) & (rgb[:, :, 1] > 180) & (rgb[:, :, 2] > 180))
        # Red needle / marker (R > 180, G < 80, B < 80, A > 100)
        red_px = np.count_nonzero((alpha > 100) & (rgb[:, :, 0] > 180) & (rgb[:, :, 1] < 80) & (rgb[:, :, 2] < 80))
        print(f"Alpha > 0 pixels: {non_zero}, Opaque pixels: {opaque}")
        print(f"White ticks / labels pixels: {white_px}")
        print(f"Red needle / marker pixels: {red_px}")
    elif img.mode == "RGB":
        rgb = arr
        # On final video frame (video background + gauge overlay):
        # White ticks / labels in the gauge area (R > 180, G > 180, B > 180)
        white_px = np.count_nonzero((rgb[:, :, 0] > 180) & (rgb[:, :, 1] > 180) & (rgb[:, :, 2] > 180))
        red_px = np.count_nonzero((rgb[:, :, 0] > 160) & (rgb[:, :, 1] < 80) & (rgb[:, :, 2] < 80))
        print(f"White pixels (ticks, labels, text): {white_px}")
        print(f"Red pixels (needle, center marker): {red_px}")

# Detailed parity check between Stage 1, Stage 3, and Stage 4:
s1 = np.array(Image.open(out_dir / "01_preview_gauge.png"))
s3 = np.array(Image.open(out_dir / "03_gpu_capture_source.png"))
s4 = np.array(Image.open(out_dir / "04_gpu_uploaded_texture.png"))

# Compare S1 (Preview crop) vs S3 (GPU capture source)
diff_1_3 = np.abs(s1.astype(int) - s3.astype(int))
print("\n" + "=" * 70)
print(f"Stage 1 vs Stage 3 Max Pixel Diff: {diff_1_3.max()}")
print(f"Stage 1 vs Stage 3 Exact Matches: {np.count_nonzero(diff_1_3 == 0)} / {diff_1_3.size} ({100 * np.count_nonzero(diff_1_3 == 0) / diff_1_3.size:.2f}%)")

# Compare S3 top 264 rows vs S4 (GPU uploaded texture)
diff_3_4 = np.abs(s3[:264, :, :].astype(int) - s4.astype(int))
print(f"Stage 3 vs Stage 4 Max Pixel Diff (overlapping HUD region): {diff_3_4.max()}")
print(f"Stage 3 vs Stage 4 Exact Matches: {np.count_nonzero(diff_3_4 == 0)} / {diff_3_4.size} ({100 * np.count_nonzero(diff_3_4 == 0) / diff_3_4.size:.2f}%)")
