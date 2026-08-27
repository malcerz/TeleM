from PIL import Image
import numpy as np

for name in ["map", "lean", "bar", "vert"]:
    ref_im = Image.open(f"scratch/crop_{name}_ref.png")
    amd_im = Image.open(f"scratch/crop_{name}_amd.png")
    
    arr_ref = np.array(ref_im)
    arr_amd = np.array(amd_im)
    
    print(f"=== REGION {name.upper()} ===")
    print(f"  REF mode={ref_im.mode}, size={ref_im.size}, non-zero alpha={np.sum(arr_ref[:,:,3] > 0) if ref_im.mode=='RGBA' else 'N/A'}")
    print(f"  AMD mode={amd_im.mode}, size={amd_im.size}, non-black RGB sum={np.sum(arr_amd > 15)}")
    
    # Save difference/visualization images
    # Extract bounding box of non-zero elements in ref
    if ref_im.mode == "RGBA":
        alpha = arr_ref[:, :, 3]
        nz_y, nz_x = np.where(alpha > 0)
        if len(nz_y) > 0:
            print(f"  REF active bbox: x=[{nz_x.min()}, {nz_x.max()}], y=[{nz_y.min()}, {nz_y.max()}]")
            # Sample pixels at center of active bbox in AMD
            cx, cy = int(np.median(nz_x)), int(np.median(nz_y))
            print(f"  REF pixel at ({cx},{cy}): {arr_ref[cy, cx]}")
            print(f"  AMD pixel at ({cx},{cy}): {arr_amd[cy, cx]}")
