import sys, subprocess
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image

out_bbox = Path('scratch/parity_bbox.mp4')
out_full = Path('scratch/parity_full.mp4')
frame_bbox_png = Path('scratch/frame_bbox_0.png')
frame_full_png = Path('scratch/frame_full_0.png')

# Extract exact frame index 0 from both
subprocess.run(["ffmpeg", "-y", "-i", str(out_bbox), "-vframes", "1", str(frame_bbox_png)], check=True, capture_output=True)
subprocess.run(["ffmpeg", "-y", "-i", str(out_full), "-vframes", "1", str(frame_full_png)], check=True, capture_output=True)

arr_bbox = np.asarray(Image.open(frame_bbox_png))
arr_full = np.asarray(Image.open(frame_full_png))

diff = np.abs(arr_bbox.astype(np.int32) - arr_full.astype(np.int32))
max_diff = int(np.max(diff))
mean_diff = float(np.mean(diff))
diff_pixels = int(np.count_nonzero(diff.any(axis=-1)))
total_pixels = arr_bbox.shape[0] * arr_bbox.shape[1]

print(f"\n[EXACT FRAME 0 PARITY METRICS (3840x2160)]")
print(f"  Max channel diff: {max_diff}")
print(f"  Mean absolute diff: {mean_diff:.6f}")
print(f"  Differing pixels: {diff_pixels} / {total_pixels} ({diff_pixels / total_pixels * 100:.3f}%)")

# Also check only the transparent background region (y: 0 to 1100)
top_diff = diff[0:1100, :]
print(f"  Top non-HUD area max diff: {np.max(top_diff)} (should be 0 - untouched background video)")

# Check HUD region (y: 1184 to 2160)
hud_diff = diff[1184:2160, :]
print(f"  HUD area max diff: {np.max(hud_diff)}, mean diff: {np.mean(hud_diff):.4f}")
