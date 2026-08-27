from PIL import Image
import numpy as np

ref_im = Image.open("scratch/reference_frame_150.png")
amd_im = Image.open("scratch/amd_frame_150.png")

arr_ref = np.array(ref_im)
arr_amd = np.array(amd_im)

# Search top right quadrant for lean pixels (X > 3200, Y < 800)
quad_ref = arr_ref[0:800, 3200:3840]
quad_amd = arr_amd[0:800, 3200:3840]

alpha_quad = quad_ref[:, :, 3]
ys, xs = np.where(alpha_quad > 0)
print(f"Lean in REF frame: X=[{xs.min() + 3200}, {xs.max() + 3200}], Y=[{ys.min()}, {ys.max()}]")

# Extract exact crop of lean from ref and amd:
x0, x1 = xs.min() + 3200, xs.max() + 3200
y0, y1 = ys.min(), ys.max()

lean_exact_ref = ref_im.crop((x0, y0, x1 + 1, y1 + 1))
lean_exact_amd = amd_im.crop((x0, y0, x1 + 1, y1 + 1))

lean_exact_ref.save("scratch/lean_exact_ref.png")
lean_exact_amd.save("scratch/lean_exact_amd.png")

# Composite ref over amd:
lean_exact_comp = lean_exact_amd.copy()
lean_exact_comp.paste(lean_exact_ref, (0, 0), lean_exact_ref)
lean_exact_comp.save("scratch/lean_exact_comp.png")

print(f"Saved lean_exact_ref.png, lean_exact_amd.png, lean_exact_comp.png")

# Check RGB values where bike is solid white in ref:
arr_lr = np.array(lean_exact_ref)
arr_la = np.array(lean_exact_amd)
white_mask = (arr_lr[:, :, 0] > 220) & (arr_lr[:, :, 1] > 220) & (arr_lr[:, :, 2] > 220) & (arr_lr[:, :, 3] > 220)
print(f"White bike pixels in exact crop: {np.sum(white_mask)}")
print(f"Mean RGB of white bike pixels in AMD: {np.mean(arr_la[white_mask], axis=0)}")
print(f"Mean RGB of white bike pixels in REF: {np.mean(arr_lr[white_mask, :3], axis=0)}")
