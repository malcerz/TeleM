import numpy as np
from pathlib import Path
from PIL import Image

FRAMES_DIR = Path("scratch/map_rotate_test/parity_frames")
cpu_im = Image.open(FRAMES_DIR / "cpu_f0000.png")
gpu_im = Image.open(FRAMES_DIR / "gpu_f0000.png")

# Let's inspect the map area: 2880, 260, 691, 691
cpu_map = cpu_im.crop((2880, 260, 2880 + 691, 260 + 691))
gpu_map = gpu_im.crop((2880, 260, 2880 + 691, 260 + 691))

cpu_map.save(FRAMES_DIR / "crop_cpu_f0000.png")
gpu_map.save(FRAMES_DIR / "crop_gpu_f0000.png")

arr_cpu = np.array(cpu_map)
arr_gpu = np.array(gpu_map)

# Check center marker:
c = 691 // 2
print(f"Center pixel (x={c}, y={c}):")
print(f"  CPU RGBA: {arr_cpu[c, c]}")
print(f"  GPU RGBA: {arr_gpu[c, c]}")

# Check corner pixel:
print(f"Corner pixel (x=10, y=10):")
print(f"  CPU RGBA: {arr_cpu[10, 10]}")
print(f"  GPU RGBA: {arr_gpu[10, 10]}")

# Mean values
print(f"Mean RGB:")
print(f"  CPU: {np.mean(arr_cpu[:, :, :3], axis=(0,1))}")
print(f"  GPU: {np.mean(arr_gpu[:, :, :3], axis=(0,1))}")
