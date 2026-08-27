from PIL import Image
import numpy as np

f = 30
img_cpu = Image.open(f"scratch/etap2g_bench/frame_cpu_{f}.png")
img_gpu = Image.open(f"scratch/etap2g_bench/frame_gpu_{f}.png")

# Crop region where lean indicator sits
crop_cpu = img_cpu.crop((3550, 320, 3840, 750))
crop_gpu = img_gpu.crop((3550, 320, 3840, 750))

crop_cpu.save(f"scratch/etap2g_bench/lean_crop_cpu_{f}.png")
crop_gpu.save(f"scratch/etap2g_bench/lean_crop_gpu_{f}.png")

diff = np.abs(np.asarray(crop_gpu).astype(np.float32) - np.asarray(crop_cpu).astype(np.float32))
Image.fromarray(np.clip(diff * 5, 0, 255).astype(np.uint8)).save(f"scratch/etap2g_bench/lean_diff_{f}.png")

print(f"Saved crops for frame {f}")
