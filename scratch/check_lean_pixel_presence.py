from PIL import Image
import numpy as np

ref = Image.open("scratch/inspect_lean_ref.png")
amd = Image.open("scratch/inspect_lean_amd.png")
exp = Image.open("scratch/inspect_lean_expected_overlay.png")

# Save direct visual inspection images
ref.save("scratch/debug_lean_ref.png")
amd.save("scratch/debug_lean_amd.png")
exp.save("scratch/debug_lean_exp.png")

# Check if the bike graphic is drawn in AMD
# The bike graphic is white/light grey with dark outlines, drawn inside (3486, 222, 3758, 494)
arr_amd = np.array(amd)
arr_ref = np.array(ref)

# Find the bbox where ref has alpha > 200
alpha = arr_ref[:, :, 3]
ys, xs = np.where(alpha > 200)
print(f"Lean active region in ref: X=[{xs.min()}, {xs.max()}], Y=[{ys.min()}, {ys.max()}]")

# Check center of bike in AMD
bike_amd = arr_amd[ys.min():ys.max()+1, xs.min():xs.max()+1]
bike_ref = arr_ref[ys.min():ys.max()+1, xs.min():xs.max()+1]
bike_exp = np.array(exp)[ys.min():ys.max()+1, xs.min():xs.max()+1]

Image.fromarray(bike_amd).save("scratch/debug_bike_actual.png")
Image.fromarray(bike_ref).save("scratch/debug_bike_ref.png")
Image.fromarray(bike_exp).save("scratch/debug_bike_exp.png")

print("Saved debug_bike_actual.png, debug_bike_ref.png, debug_bike_exp.png")
