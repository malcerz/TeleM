import subprocess
import os
import numpy as np
from PIL import Image
from pathlib import Path

OUT_DIR = Path("scratch/etap2g_bench")
FFMPEG = r"C:\tools\ffmpeg.exe"

def extract_frame(video_path: str, frame_num: int, out_png: str):
    cmd = [
        FFMPEG, "-y",
        "-i", video_path,
        "-vf", f"select=eq(n\\,{frame_num})",
        "-vframes", "1",
        out_png
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def main():
    cpu_vid = str(OUT_DIR / "lean_cpu_300f.mp4")
    gpu_vid = str(OUT_DIR / "lean_gpu_300f.mp4")

    frames_to_check = [30, 60, 120, 180, 240, 290]

    print("=" * 80)
    print("ETAP 2G VISUAL PARITY & GHOSTING CHECK")
    print("=" * 80)

    for f in frames_to_check:
        cpu_png = str(OUT_DIR / f"frame_cpu_{f}.png")
        gpu_png = str(OUT_DIR / f"frame_gpu_{f}.png")
        extract_frame(cpu_vid, f, cpu_png)
        extract_frame(gpu_vid, f, gpu_png)

        # Crop lean widget area: in def_layout.json, lean_indicator is at x=0.97, y=0.18 -> approx (3600..3840, 300..800)
        img_cpu = Image.open(cpu_png)
        img_gpu = Image.open(gpu_png)

        # Lean indicator region: (3500, 300, 3840, 800)
        crop_cpu = img_cpu.crop((3500, 300, 3840, 800))
        crop_gpu = img_gpu.crop((3500, 300, 3840, 800))

        arr_cpu = np.asarray(crop_cpu).astype(np.float32)
        arr_gpu = np.asarray(crop_gpu).astype(np.float32)

        diff = np.abs(arr_gpu - arr_cpu)
        mae = np.mean(diff)
        max_diff = np.max(diff)
        n_diff = np.count_nonzero(diff > 5.0)

        print(f"Frame {f:3d}: Lean region MAE = {mae:.3f}, MaxDiff = {max_diff:.1f}, px diff (>5) = {n_diff}")

    print("=" * 80)

if __name__ == "__main__":
    main()
