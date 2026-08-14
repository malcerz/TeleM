import os
import subprocess
import numpy as np
from PIL import Image

output_mp4 = os.path.abspath("Video/GX020079_real_gui_export_3c.mp4")

print("=================================================================")
print("  FINAL MP4 VISUAL & TELEMETRY VERIFICATION                      ")
print("=================================================================")

for frame_no, ss_time in [(30, "1.0"), (50, "1.6"), (90, "3.0")]:
    out_img = f"frame_{frame_no}_final.png"
    cmd = [
        r"c:\tools\ffmpeg.exe", "-y",
        "-ss", ss_time,
        "-i", output_mp4,
        "-vframes", "1",
        out_img
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if os.path.exists(out_img):
        im = Image.open(out_img)
        arr = np.array(im)
        print(f"\nFrame {frame_no} ({ss_time}s) extracted -> {out_img}:")
        print(f"  Shape: {arr.shape}, Dtype: {arr.dtype}")
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        print(f"  Min: {arr.min()}, Max: {arr.max()}, Mean: {arr.mean():.2f}")
        print(f"  RGB Means -> R: {r.mean():.2f}, G: {g.mean():.2f}, B: {b.mean():.2f}")
        print(f"  RGB Max   -> R: {r.max()}, G: {g.max()}, B: {b.max()}")
        print(f"  Non-black (>20) pixels: {(arr > 20).sum()} / {arr.size} ({((arr > 20).sum() / arr.size) * 100:.1f}%)")
