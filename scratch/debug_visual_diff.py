"""Script to analyze exact visual differences between Golden Reference and AMD Multi-Region output.
"""

from __future__ import annotations

import json
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

    diff = np.abs(ref_arr.astype(np.int16) - amd_arr.astype(np.int16))
    diff_mask = np.max(diff, axis=2) > 30

    print("Diff map shape:", diff_mask.shape)
    # Find bounding box of all differing pixels
    ys, xs = np.where(diff_mask)
    if len(xs) > 0:
        print(f"Diff Y range: {np.min(ys)} to {np.max(ys)}")
        print(f"Diff X range: {np.min(xs)} to {np.max(xs)}")
    else:
        print("No pixel differences > 30!")

    # Check top-left (time_block)
    tl_diff = diff_mask[0:400, 0:800]
    print(f"Top-Left (Time Block) Diff Pixels: {np.sum(tl_diff)}")

    # Check bottom-right (charts/maps)
    br_diff = diff_mask[1600:2160, 2400:3840]
    print(f"Bottom-Right (Map/Charts) Diff Pixels: {np.sum(br_diff)}")

    # Check bottom-bar (speed, hr, cadence)
    bb_diff = diff_mask[1600:2160, 0:2400]
    print(f"Bottom-Bar (Speed/HR/Cadence) Diff Pixels: {np.sum(bb_diff)}")

    # Save a high contrast diff visualization
    vis = np.zeros_like(ref_arr)
    vis[diff_mask] = [255, 0, 0]  # Red pixels where AMD differs from Reference
    Image.fromarray(vis).save("scratch/visual_compare/diff_visualization_30.png")
    print("Saved scratch/visual_compare/diff_visualization_30.png")

if __name__ == "__main__":
    main()
