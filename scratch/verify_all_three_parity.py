import json
import sys
from PIL import Image
import numpy as np

# Load reference and AMD frames
ref = Image.open("scratch/reference_frame_150.png")
amd = Image.open("scratch/amd_frame_150.png")

print(f"Ref size: {ref.size}, AMD size: {amd.size}")

# 1. MAP PARITY
# Reference map bbox: (51, 428, 691, 691) -> x=[51, 742], y=[428, 1119]
map_ref = ref.crop((51, 428, 742, 1119))
map_amd = amd.crop((51, 428, 742, 1119))
map_ref.save("scratch/parity_map_ref.png")
map_amd.save("scratch/parity_map_amd.png")

arr_mr = np.array(map_ref)
arr_ma = np.array(map_amd)
map_active = arr_mr[:, :, 3] > 0
print(f"MAP: active pixels={np.sum(map_active)} / {691*691}")
print(f"MAP: Mean color in ref={np.mean(arr_mr[map_active, :3], axis=0)}")
print(f"MAP: Mean color in amd={np.mean(arr_ma[map_active], axis=0)}")

# 2. LEAN PARITY
# Reference lean bbox: x=[3468, 3775], y=[204, 510]
lean_ref = ref.crop((3468, 204, 3776, 511))
lean_amd = amd.crop((3468, 204, 3776, 511))
lean_ref.save("scratch/parity_lean_ref.png")
lean_amd.save("scratch/parity_lean_amd.png")

arr_lr = np.array(lean_ref)
arr_la = np.array(lean_amd)
lean_active = arr_lr[:, :, 3] > 0
print(f"\nLEAN: active pixels={np.sum(lean_active)}")
print(f"LEAN: Mean color in ref={np.mean(arr_lr[lean_active, :3], axis=0)}")
print(f"LEAN: Mean color in amd={np.mean(arr_la[lean_active], axis=0)}")

# 3. HORIZONTAL BAR (fit_distance_text)
# Bbox: (840, 93, 2324, 210) -> x=[840, 3164], y=[93, 303]
bar_ref = ref.crop((840, 93, 3164, 303))
bar_amd = amd.crop((840, 93, 3164, 303))
bar_ref.save("scratch/parity_bar_ref.png")
bar_amd.save("scratch/parity_bar_amd.png")

arr_br = np.array(bar_ref)
arr_ba = np.array(bar_amd)
bar_active = arr_br[:, :, 3] > 0
solid_bar = arr_br[:, :, 3] == 255
diff_bar_solid = np.abs(arr_br[solid_bar, :3].astype(int) - arr_ba[solid_bar].astype(int))
print(f"\nBAR HORIZONTAL (fit_distance_text): active pixels={np.sum(bar_active)}, solid={np.sum(solid_bar)}")
print(f"BAR: max diff on solid pixels={np.max(diff_bar_solid)}, mean diff={np.mean(diff_bar_solid):.2f}")

# 4. VERTICAL BAR (alt_text)
# Bbox: (3437, 933, 386, 213) -> x=[3437, 3823], y=[933, 1146]
vert_ref = ref.crop((3437, 933, 3823, 1146))
vert_amd = amd.crop((3437, 933, 3823, 1146))
vert_ref.save("scratch/parity_vert_ref.png")
vert_amd.save("scratch/parity_vert_amd.png")

arr_vr = np.array(vert_ref)
arr_va = np.array(vert_amd)
vert_active = arr_vr[:, :, 3] > 0
solid_vert = arr_vr[:, :, 3] == 255
diff_vert_solid = np.abs(arr_vr[solid_vert, :3].astype(int) - arr_va[solid_vert].astype(int))
print(f"\nBAR VERTICAL (alt_text): active pixels={np.sum(vert_active)}, solid={np.sum(solid_vert)}")
print(f"VERT: max diff on solid pixels={np.max(diff_vert_solid)}, mean diff={np.mean(diff_vert_solid):.2f}")
