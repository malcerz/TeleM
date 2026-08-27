import os
import sys
import math
import subprocess
import numpy as np
from pathlib import Path
from PIL import Image

OUT_DIR = Path("scratch/map_rotate_test")
CPU_MP4 = OUT_DIR / "test_rotate_cpu_120f.mp4"
GPU_MP4 = OUT_DIR / "test_rotate_gpu_120f.mp4"
FRAMES_DIR = OUT_DIR / "parity_frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

def extract_frame(mp4_path: Path, frame_idx: int, out_png: Path):
    cmd = [
        "ffmpeg", "-y", "-i", str(mp4_path),
        "-vf", f"select=eq(n\\,{frame_idx})",
        "-vframes", "1",
        str(out_png)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def calculate_metrics(img1_path: Path, img2_path: Path, crop_bbox=None):
    im1 = Image.open(img1_path).convert("RGBA")
    im2 = Image.open(img2_path).convert("RGBA")
    if crop_bbox:
        im1 = im1.crop(crop_bbox)
        im2 = im2.crop(crop_bbox)
    
    a1 = np.array(im1, dtype=np.float32)
    a2 = np.array(im2, dtype=np.float32)
    
    diff = np.abs(a1 - a2)
    max_diff = np.max(diff)
    mae = np.mean(diff)
    mse = np.mean((a1 - a2) ** 2)
    psnr = 100.0 if mse == 0 else 20 * math.log10(255.0 / math.sqrt(mse))
    diff_pixels = np.sum(np.any(diff > 0, axis=-1))
    total_pixels = a1.shape[0] * a1.shape[1]
    
    return {
        "max_diff": float(max_diff),
        "mae": float(mae),
        "mse": float(mse),
        "psnr": float(psnr),
        "diff_pixels": int(diff_pixels),
        "total_pixels": int(total_pixels),
        "diff_pct": float(diff_pixels / total_pixels * 100.0)
    }

def main():
    test_frames = [0, 10, 30, 60, 119]
    print(f"{'Frame':<8} {'Max Diff':<10} {'MAE':<10} {'PSNR (dB)':<12} {'Diff Px %':<12} {'Status'}")
    print("-" * 65)
    
    # Map bbox in 3840x2160 (x=84%, y=28%, size=18% -> 691x691 at ~3225, 605)
    # Let's crop full map region
    for f in test_frames:
        cpu_png = FRAMES_DIR / f"cpu_f{f:04d}.png"
        gpu_png = FRAMES_DIR / f"gpu_f{f:04d}.png"
        diff_png = FRAMES_DIR / f"diff_f{f:04d}.png"
        
        extract_frame(CPU_MP4, f, cpu_png)
        extract_frame(GPU_MP4, f, gpu_png)
        
        # Full frame metrics
        m_full = calculate_metrics(cpu_png, gpu_png)
        
        # Save diff visualization
        im_cpu = Image.open(cpu_png).convert("RGBA")
        im_gpu = Image.open(gpu_png).convert("RGBA")
        arr_diff = np.abs(np.array(im_cpu, dtype=np.int16) - np.array(im_gpu, dtype=np.int16))
        arr_vis = np.clip(arr_diff * 10, 0, 255).astype(np.uint8)
        arr_vis[:, :, 3] = 255
        Image.fromarray(arr_vis).save(diff_png)
        
        status = "PASS" if m_full["psnr"] > 35.0 or m_full["mae"] < 2.0 else "REVIEW"
        print(f"{f:<8} {m_full['max_diff']:<10.1f} {m_full['mae']:<10.3f} {m_full['psnr']:<12.2f} {m_full['diff_pct']:<12.2f}% {status}")

if __name__ == "__main__":
    main()
