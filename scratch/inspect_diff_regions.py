"""Inspect diff areas in detail between Golden Reference and AMD Multi-Region frame 15.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

def main():
    ref_img = Image.open("scratch/visual_compare/ref_frame_15.png")
    amd_img = Image.open("scratch/visual_compare/amd_frame_15.png")

    ref_arr = np.array(ref_img)
    amd_arr = np.array(amd_img)

    # Convert to grayscale for structural similarity analysis
    diff_abs = np.abs(ref_arr.astype(np.float32) - amd_arr.astype(np.float32))
    max_chan_diff = np.max(diff_abs, axis=2)

    # Significant differences (> 40 in any color channel)
    sig_mask = max_chan_diff > 40
    ys, xs = np.where(sig_mask)

    print(f"Total pixels with >40 channel difference: {len(xs)}")
    if len(xs) > 0:
        print(f"Significant Diff X range: {np.min(xs)} .. {np.max(xs)}")
        print(f"Significant Diff Y range: {np.min(ys)} .. {np.max(ys)}")

    # Crop the time_block region (x=0..600, y=0..350) from both
    ref_tb = ref_arr[20:350, 20:600]
    amd_tb = amd_arr[20:350, 20:600]

    Image.fromarray(ref_tb).save("scratch/visual_compare/ref_timeblock.png")
    Image.fromarray(amd_tb).save("scratch/visual_compare/amd_timeblock.png")

    # Crop the bottom-bar region (x=600..3840, y=1700..2160) from both
    ref_bb = ref_arr[1700:2160, 600:3840]
    amd_bb = amd_arr[1700:2160, 600:3840]

    Image.fromarray(ref_bb).save("scratch/visual_compare/ref_bottombar.png")
    Image.fromarray(amd_bb).save("scratch/visual_compare/amd_bottombar.png")

    # Crop the top-right region (x=3200..3840, y=400..900) from both
    ref_tr = ref_arr[400:900, 3200:3840]
    amd_tr = amd_arr[400:900, 3200:3840]

    Image.fromarray(ref_tr).save("scratch/visual_compare/ref_topright.png")
    Image.fromarray(amd_tr).save("scratch/visual_compare/amd_topright.png")

    print("Saved cropped region comparisons in scratch/visual_compare/")

if __name__ == "__main__":
    main()
