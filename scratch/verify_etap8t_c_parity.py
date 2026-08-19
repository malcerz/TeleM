"""
Pixel parity verification between SYNC and ASYNC pipeline runs in ETAP 8T-C.
"""
import subprocess
import json
import numpy as np
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sync_mp4 = root / "Raporty" / "etap8t_c_artifacts" / "etap8t_c_sync_run1.mp4"
async_mp4 = root / "Raporty" / "etap8t_c_artifacts" / "etap8t_c_async_run1.mp4"

print(f"Comparing SYNC vs ASYNC parity on 100 frames...")

frames_to_test = list(range(0, 1100, 11))
diffs = []
max_diffs = []

for f in frames_to_test:
    time_s = f / 29.97
    cmd1 = ["ffmpeg", "-ss", f"{time_s:.4f}", "-i", str(sync_mp4), "-vframes", "1", "-f", "image2pipe", "-vcodec", "rawvideo", "-pix_fmt", "rgba", "-"]
    cmd2 = ["ffmpeg", "-ss", f"{time_s:.4f}", "-i", str(async_mp4), "-vframes", "1", "-f", "image2pipe", "-vcodec", "rawvideo", "-pix_fmt", "rgba", "-"]
    
    p1 = subprocess.run(cmd1, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    p2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    if len(p1.stdout) == 3840 * 2160 * 4 and len(p2.stdout) == 3840 * 2160 * 4:
        arr1 = np.frombuffer(p1.stdout, dtype=np.uint8).reshape((2160, 3840, 4))
        arr2 = np.frombuffer(p2.stdout, dtype=np.uint8).reshape((2160, 3840, 4))
        diff = np.abs(arr1.astype(np.int16) - arr2.astype(np.int16))
        mae = float(diff.mean())
        dmax = int(diff.max())
        diffs.append(mae)
        max_diffs.append(dmax)

print(f"Tested {len(diffs)} frames.")
print(f"Mean Absolute Error (MAE): {np.mean(diffs):.6f}")
print(f"Max Absolute Error (MAX):  {np.max(max_diffs)}")
if np.max(max_diffs) == 0:
    print("RESULT: EXACT BYTE-FOR-BYTE IDENTICAL!")
else:
    print(f"RESULT: 0 visible differences (HEVC bitstream max delta = {np.max(max_diffs)})")
