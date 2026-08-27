from PIL import Image
import numpy as np

vert_ref = Image.open("scratch/inspect_vert_ref.png")
vert_amd = Image.open("scratch/inspect_vert_amd.png")

# Find bounding box of non-zero pixels in vert_ref
arr_ref = np.array(vert_ref)
arr_amd = np.array(vert_amd)

alpha = arr_ref[:, :, 3]
nz_y, nz_x = np.where(alpha > 0)
print(f"VERT REF active bbox: X=[{nz_x.min()}, {nz_x.max()}], Y=[{nz_y.min()}, {nz_y.max()}]")

# Crop the active region:
crop_v_ref = vert_ref.crop((nz_x.min(), nz_y.min(), nz_x.max()+1, nz_y.max()+1))
crop_v_amd = vert_amd.crop((nz_x.min(), nz_y.min(), nz_x.max()+1, nz_y.max()+1))

crop_v_ref.save("scratch/debug_vert_crop_ref.png")
crop_v_amd.save("scratch/debug_vert_crop_amd.png")

# Also composite ref onto amd
comp = crop_v_amd.copy()
comp.paste(crop_v_ref, (0, 0), crop_v_ref)
comp.save("scratch/debug_vert_crop_expected.png")

print("Saved debug_vert_crop_ref.png, debug_vert_crop_amd.png, debug_vert_crop_expected.png")
