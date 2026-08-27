import math
import numpy as np
from pathlib import Path
from PIL import Image

OUT_DIR = Path("scratch/map_rotate_test")
FRAMES_DIR = OUT_DIR / "parity_frames"

def analyze():
    # Map bbox in cycling_dashboard_v10:
    # size = 18% of 3840 = 691x691
    # x = 84% -> rx = 3225, ry = 28% -> 605
    # dst_bbox = (3225 - 345, 605 - 345, 691, 691) = (2880, 260, 691, 691)
    map_bbox = (2880, 260, 2880 + 691, 260 + 691)
    
    print("=== MAP WIDGET REGION PARITY ===")
    print(f"{'Frame':<8} {'Max Diff':<10} {'MAE':<10} {'PSNR (dB)':<12} {'Diff Px %':<12}")
    print("-" * 55)
    
    for f in [0, 10, 30, 60, 119]:
        cpu_im = Image.open(FRAMES_DIR / f"cpu_f{f:04d}.png").convert("RGBA").crop(map_bbox)
        gpu_im = Image.open(FRAMES_DIR / f"gpu_f{f:04d}.png").convert("RGBA").crop(map_bbox)
        
        a1 = np.array(cpu_im, dtype=np.float32)
        a2 = np.array(gpu_im, dtype=np.float32)
        
        diff = np.abs(a1 - a2)
        max_diff = np.max(diff)
        mae = np.mean(diff)
        mse = np.mean((a1 - a2) ** 2)
        psnr = 100.0 if mse == 0 else 20 * math.log10(255.0 / math.sqrt(mse))
        diff_pixels = np.sum(np.any(diff > 0, axis=-1))
        total_pixels = a1.shape[0] * a1.shape[1]
        
        # Save map crop side-by-side
        combined = Image.new("RGBA", (691 * 3, 691))
        combined.paste(cpu_im, (0, 0))
        combined.paste(gpu_im, (691, 0))
        diff_vis = Image.fromarray(np.clip(diff[:, :, :3] * 10, 0, 255).astype(np.uint8))
        combined.paste(diff_vis, (691 * 2, 0))
        combined.save(FRAMES_DIR / f"map_comparison_f{f:04d}.png")
        
        print(f"{f:<8} {max_diff:<10.1f} {mae:<10.3f} {psnr:<12.2f} {diff_pixels/total_pixels*100.0:<12.2f}%")

if __name__ == "__main__":
    analyze()
