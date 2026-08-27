from PIL import Image
import numpy as np

sub_ref = Image.open("scratch/bar_sub_ref.png")
sub_amd = Image.open("scratch/bar_sub_amd.png")

arr_ref = np.array(sub_ref)
arr_amd = np.array(sub_amd)

# In ref, let's look at lines and text:
# Alpha channel
alpha = arr_ref[:, :, 3]

# Where is marker? In ref, find brightest or specific colored pixels
# Where is text?
print(f"Total non-zero alpha pixels in ref: {np.sum(alpha > 0)}")

# Check in AMD how many pixels match or differ
# Notice AMD has video underneath!
# For solid pixels (alpha == 255):
solid = alpha == 255
print(f"Solid pixels count: {np.sum(solid)}")

# Compare RGB difference on solid white text/tick pixels
ref_rgb = arr_ref[solid, :3]
amd_rgb = arr_amd[solid, :3]

diff_solid = np.abs(ref_rgb.astype(int) - amd_rgb.astype(int))
print(f"Max diff on solid pixels: {np.max(diff_solid)}")
print(f"Mean diff on solid pixels: {np.mean(diff_solid):.2f}")
print(f"Pixels with diff > 30 on solid pixels: {np.sum(diff_solid > 30)}")

# Let's check vertical bar (alt_text) as well:
vert_ref = Image.open("scratch/inspect_vert_ref.png")
vert_amd = Image.open("scratch/inspect_vert_amd.png")
arr_v_ref = np.array(vert_ref)
arr_v_amd = np.array(vert_amd)
alpha_v = arr_v_ref[:, :, 3]
solid_v = alpha_v == 255
print(f"\nVertical bar solid pixels count: {np.sum(solid_v)}")
if np.sum(solid_v) > 0:
    diff_v = np.abs(arr_v_ref[solid_v, :3].astype(int) - arr_v_amd[solid_v, :3].astype(int))
    print(f"Max diff on vertical bar solid pixels: {np.max(diff_v)}")
    print(f"Mean diff on vertical bar solid pixels: {np.mean(diff_v):.2f}")
