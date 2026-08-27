from PIL import Image
import numpy as np

for name in ["map", "lean", "bar", "vert"]:
    ref_im = Image.open(f"scratch/inspect_{name}_ref.png")
    amd_im = Image.open(f"scratch/inspect_{name}_amd.png")
    exp_im = Image.open(f"scratch/inspect_{name}_expected_overlay.png")
    
    arr_ref = np.array(ref_im)
    arr_amd = np.array(amd_im)
    arr_exp = np.array(exp_im)
    
    # Calculate difference between amd (actual) and exp (expected)
    diff = np.abs(arr_amd.astype(int) - arr_exp.astype(int))
    max_d = np.max(diff)
    mae = np.mean(diff)
    nz_ref = np.sum(arr_ref[:, :, 3] > 0)
    
    print(f"=== {name.upper()} ANALYSIS ===")
    print(f"  Reference non-zero alpha pixels: {nz_ref}")
    print(f"  Actual vs Expected MaxDiff: {max_d}, MAE: {mae:.2f}")
    
    # Check specific features
    if name == "map":
        # Check if map satellite tiles/track line are present in AMD
        print(f"  Map center region mean color in AMD: {np.mean(arr_amd[150:300, 150:300], axis=(0,1))}")
        print(f"  Map center region mean color in EXP: {np.mean(arr_exp[150:300, 150:300], axis=(0,1))}")
    elif name == "lean":
        # Check lean icon presence
        print(f"  Lean center region in AMD: {np.mean(arr_amd[100:170, 100:170], axis=(0,1))}")
        print(f"  Lean center region in EXP: {np.mean(arr_exp[100:170, 100:170], axis=(0,1))}")
    elif name == "bar":
        # Check horizontal ruler
        # Find where ticks/ruler lines are in ref
        ruler_mask = arr_ref[:, :, 3] > 100
        print(f"  Bar ruler mask active pixels: {np.sum(ruler_mask)}")
        # Compare pixels where ref has ruler lines vs amd
        diff_on_ruler = np.mean(np.abs(arr_amd[ruler_mask].astype(int) - arr_exp[ruler_mask].astype(int)))
        print(f"  Mean diff on ruler pixels: {diff_on_ruler:.2f}")
