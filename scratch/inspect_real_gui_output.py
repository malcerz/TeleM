"""Inspect real GUI output and investigate issues A, B, C."""
import json
import subprocess
from pathlib import Path
from PIL import Image

root = Path("c:/_DEV/TeleM")
mp4_path = root / "Video" / "output_h265.mp4"

def extract_and_inspect_frames():
    print(f"=== INSPECTING {mp4_path} ===")
    out_dir = root / "scratch" / "gui_export_inspection"
    out_dir.mkdir(exist_ok=True)
    
    # Extract frames 30, 225, 450, 1000, 2500, 5000
    frames = [30, 225, 450, 1000, 2500, 5000]
    for f in frames:
        png_path = out_dir / f"frame_{f:04d}.png"
        pts = f * (1001 / 30000)
        cmd = [
            r"C:\tools\ffmpeg.exe", "-y", "-ss", f"{pts:.3f}", "-i", str(mp4_path),
            "-vframes", "1", "-q:v", "2", str(png_path)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if png_path.exists():
            img = Image.open(png_path)
            print(f"Extracted frame {f}: size={img.size}")
            
            # Crop map region (around x=88%, y=22% -> x~3379, y~481, w~691, h~691)
            # Layout: x=88.02%, y=22.31%, size=18% of 3840 = 691.2 -> dst_bbox=(3035, 137, 691, 691)
            map_crop = img.crop((3000, 100, 3800, 900))
            map_crop.save(out_dir / f"map_crop_{f:04d}.png")
            
            # Crop Battery & Solar text region (x=85.96%, y=43.33% and x=50%, y=8%)
            bat_crop = img.crop((3250, 900, 3800, 1050))
            bat_crop.save(out_dir / f"bat_crop_{f:04d}.png")

            solar_crop = img.crop((1800, 100, 2100, 250))
            solar_crop.save(out_dir / f"solar_crop_{f:04d}.png")

if __name__ == "__main__":
    extract_and_inspect_frames()
