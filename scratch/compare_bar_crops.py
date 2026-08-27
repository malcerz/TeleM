from PIL import Image
import numpy as np

ref_im = Image.open("scratch/inspect_bar_ref.png")
amd_im = Image.open("scratch/inspect_bar_amd.png")

print(f"ref size: {ref_im.size}, amd size: {amd_im.size}")
arr_ref = np.array(ref_im)
arr_amd = np.array(amd_im)

# ref has alpha channel
alpha = arr_ref[:, :, 3]
active_y, active_x = np.where(alpha > 0)
print(f"REF BAR active range: X=[{active_x.min()}, {active_x.max()}], Y=[{active_y.min()}, {active_y.max()}]")

# Check AMD image in the same active range:
# Extract only the RGB where alpha > 0
sub_ref = arr_ref[active_y.min():active_y.max()+1, active_x.min():active_x.max()+1]
sub_amd = arr_amd[active_y.min():active_y.max()+1, active_x.min():active_x.max()+1]

# Save sub crops
Image.fromarray(sub_ref).save("scratch/bar_sub_ref.png")
Image.fromarray(sub_amd).save("scratch/bar_sub_amd.png")

# Composite ref onto amd for visual comparison
composite = Image.fromarray(sub_amd[:,:,:3]).copy()
ref_rgba = Image.fromarray(sub_ref)
composite.paste(ref_rgba, (0,0), ref_rgba)
composite.save("scratch/bar_sub_expected.png")

print("Saved bar_sub_ref.png, bar_sub_amd.png, bar_sub_expected.png")
