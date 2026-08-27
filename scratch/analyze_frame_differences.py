import sys
from pathlib import Path
from PIL import Image
import numpy as np

repo_root = Path(__file__).resolve().parents[1]

p_ref = repo_root / "scratch" / "reference_frame_150.png"
p_amd = repo_root / "scratch" / "amd_frame_150.png"

ref = Image.open(p_ref).convert("RGBA")
amd = Image.open(p_amd).convert("RGBA")

print(f"Reference size: {ref.size}, AMD size: {amd.size}")

# Let's inspect crops:
# 1. MAP region (top-left: x=[50, 1000], y=[50, 1000])
map_crop_ref = ref.crop((50, 50, 1000, 1000))
map_crop_amd = amd.crop((50, 50, 1000, 1000))
map_crop_ref.save(repo_root / "scratch" / "crop_map_ref.png")
map_crop_amd.save(repo_root / "scratch" / "crop_map_amd.png")

# 2. LEAN region (top-right: x=[2800, 3800], y=[50, 1000])
lean_crop_ref = ref.crop((2800, 50, 3800, 1000))
lean_crop_amd = amd.crop((2800, 50, 3800, 1000))
lean_crop_ref.save(repo_root / "scratch" / "crop_lean_ref.png")
lean_crop_amd.save(repo_root / "scratch" / "crop_lean_amd.png")

# 3. BAR region (bottom horizontal ruler: x=[500, 3300], y=[1800, 2150])
bar_crop_ref = ref.crop((500, 1800, 3300, 2150))
bar_crop_amd = amd.crop((500, 1800, 3300, 2150))
bar_crop_ref.save(repo_root / "scratch" / "crop_bar_ref.png")
bar_crop_amd.save(repo_root / "scratch" / "crop_bar_amd.png")

# 4. Vertical ruler (left vertical ruler: x=[50, 500], y=[500, 1800])
vert_crop_ref = ref.crop((50, 500, 500, 1800))
vert_crop_amd = amd.crop((50, 500, 500, 1800))
vert_crop_ref.save(repo_root / "scratch" / "crop_vert_ref.png")
vert_crop_amd.save(repo_root / "scratch" / "crop_vert_amd.png")

print("Saved crop images to scratch/ for visual inspection.")

# Check non-zero alpha pixels in crops:
arr_map_ref = np.array(map_crop_ref)
arr_map_amd = np.array(map_crop_amd)
print(f"Map ref non-transparent pixels: {np.sum(arr_map_ref[:,:,3] > 0)}")
print(f"Map amd non-black pixels: {np.sum(arr_map_amd[:,:,:3] > 30)}")

arr_lean_ref = np.array(lean_crop_ref)
arr_lean_amd = np.array(lean_crop_amd)
print(f"Lean ref non-transparent pixels: {np.sum(arr_lean_ref[:,:,3] > 0)}")
print(f"Lean amd non-black pixels: {np.sum(arr_lean_amd[:,:,:3] > 30)}")
