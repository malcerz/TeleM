from PIL import Image
import numpy as np

im_amd = Image.open("scratch/lean_exact_amd.png")
im_ref = Image.open("scratch/lean_exact_ref.png")

print(f"im_amd size: {im_amd.size}, mode: {im_amd.mode}")
print(f"im_ref size: {im_ref.size}, mode: {im_ref.mode}")

# Let's save a side-by-side comparison:
combined = Image.new("RGB", (im_amd.width * 2 + 10, im_amd.height), (50, 50, 50))
combined.paste(im_ref.convert("RGB"), (0, 0))
combined.paste(im_amd.convert("RGB"), (im_amd.width + 10, 0))
combined.save("scratch/debug_lean_side_by_side.png")
print("Saved debug_lean_side_by_side.png")

# Let's find any white pixels in im_amd:
arr_a = np.array(im_amd)
white_in_amd = np.sum((arr_a[:,:,0] > 240) & (arr_a[:,:,1] > 240) & (arr_a[:,:,2] > 240))
print(f"White pixels (>240) in AMD lean crop: {white_in_amd}")

# In ref:
arr_r = np.array(im_ref)
white_in_ref = np.sum((arr_r[:,:,0] > 240) & (arr_r[:,:,1] > 240) & (arr_r[:,:,2] > 240))
print(f"White pixels (>240) in REF lean crop: {white_in_ref}")
