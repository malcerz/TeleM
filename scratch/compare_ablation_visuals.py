"""Compare decoded video frames between baseline (2 passes), 1 pass, and bypass (0 passes)."""
import subprocess
import sys
from pathlib import Path
import numpy as np

root = Path("c:/_DEV/TeleM")

def extract_frame_png(video_path: Path, frame_idx: int, out_png: Path):
    cmd = [
        r"C:\tools\ffmpeg.exe", "-y",
        "-ss", f"{frame_idx * (1001/30000):.4f}",
        "-i", str(video_path),
        "-vframes", "1",
        str(out_png)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

from PIL import Image

def analyze_visual_comparison():
    print("=== VISUAL AND STATISTICAL COMPARISON ACROSS ABLATIONS ===")
    runs = {
        "Baseline (2 passes)": root / "scratch" / "run_passes_2_baseline.mp4",
        "Studio (1 pass)": root / "scratch" / "run_passes_1_studio.mp4",
        "Bypass (0 passes)": root / "scratch" / "run_passes_0_bypass.mp4",
    }
    
    test_frames = [30, 225, 450, 675, 850]
    
    for f in test_frames:
        print(f"\n--- FRAME {f:3d} VISUAL ANALYSIS ---")
        imgs = {}
        arrs = {}
        for r_name, v_path in runs.items():
            out_png = root / "scratch" / f"compare_{r_name.split()[0].lower()}_frame_{f}.png"
            extract_frame_png(v_path, f, out_png)
            img = Image.open(out_png).convert("RGB")
            arr = np.array(img, dtype=np.float32)
            imgs[r_name] = img
            arrs[r_name] = arr
            
            # Compute luminance Y from RGB
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            y_luma = 0.299 * r + 0.587 * g + 0.114 * b
            print(f"  [{r_name:20s}] RGB Luma Y: min={np.min(y_luma):5.1f}, max={np.max(y_luma):5.1f}, mean={np.mean(y_luma):5.1f}, p01={np.percentile(y_luma, 1):5.1f}, p99={np.percentile(y_luma, 99):5.1f}")
        
        base_arr = arrs["Baseline (2 passes)"]
        for r_name in ["Studio (1 pass)", "Bypass (0 passes)"]:
            arr = arrs[r_name]
            mae = np.mean(np.abs(arr - base_arr))
            max_diff = np.max(np.abs(arr - base_arr))
            mse = np.mean((arr - base_arr) ** 2)
            psnr = 20 * np.log10(255.0 / np.sqrt(mse)) if mse > 0 else 999.0
            print(f"  Diff {r_name:20s} vs Baseline: MAE={mae:5.2f}, MaxDiff={max_diff:5.1f}, PSNR={psnr:5.2f} dB")


if __name__ == "__main__":
    analyze_visual_comparison()
