"""Check map region across video frames."""
import subprocess
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
mp4_p = root / "Video" / "output_h265.mp4"
out_dir = root / "scratch" / "map_series"
out_dir.mkdir(exist_ok=True)

def extract_and_check():
    for f in [0, 500, 1000, 2000, 3000, 4000, 5000]:
        pts = f * (1001 / 30000)
        p = out_dir / f"f_{f:04d}.png"
        subprocess.run([
            r"C:\tools\ffmpeg.exe", "-y", "-ss", f"{pts:.3f}", "-i", str(mp4_p),
            "-vframes", "1", "-q:v", "2", str(p)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if p.exists():
            img = Image.open(p)
            map_crop = img.crop((3035, 137, 3035 + 691, 137 + 691))
            map_crop.save(out_dir / f"map_{f:04d}.png")
            arr = np.array(map_crop)
            print(f"Frame {f:4d}: min={arr.min()}, max={arr.max()}, mean={arr.mean():.2f}")

if __name__ == "__main__":
    extract_and_check()
