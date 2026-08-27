from PIL import Image
import numpy as np

actual = Image.open("scratch/debug_bike_actual.png")
ref = Image.open("scratch/debug_bike_ref.png")
exp = Image.open("scratch/debug_bike_exp.png")

arr_act = np.array(actual)
arr_ref = np.array(ref)
arr_exp = np.array(exp)

print("actual shape:", arr_act.shape)
print("ref shape:", arr_ref.shape)

# Let's find bike rider outline (alpha == 255 and color is near white (255,255,255) or black)
mask_white = (arr_ref[:,:,0] > 200) & (arr_ref[:,:,1] > 200) & (arr_ref[:,:,2] > 200) & (arr_ref[:,:,3] > 200)
print(f"White bike pixels in ref: {np.sum(mask_white)}")

# In actual AMD image:
act_white_mean = np.mean(arr_act[mask_white], axis=0) if np.sum(mask_white) > 0 else 0
exp_white_mean = np.mean(arr_exp[mask_white], axis=0) if np.sum(mask_white) > 0 else 0
print(f"Mean RGB of bike pixels in actual AMD: {act_white_mean}")
print(f"Mean RGB of bike pixels in expected:   {exp_white_mean}")
