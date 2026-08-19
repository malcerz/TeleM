"""Compare CPU working map image vs Video crop image."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
cpu_p = root / "scratch" / "gui_export_inspection" / "cpu_working_map.png"
vid_p = root / "scratch" / "gui_export_inspection" / "vid_dst_bbox_crop.png"

def compare():
    img_cpu = Image.open(cpu_p)
    img_vid = Image.open(vid_p)
    print(f"CPU working map: size={img_cpu.size}, mode={img_cpu.mode}")
    print(f"Video crop map:  size={img_vid.size}, mode={img_vid.mode}")

    # Check alpha channel of CPU working map
    arr_cpu = np.array(img_cpu)
    print(f"CPU map Alpha: min={arr_cpu[:, :, 3].min()}, max={arr_cpu[:, :, 3].max()}, mean={arr_cpu[:, :, 3].mean():.2f}")
    
    # Check non-zero alpha bbox of CPU map
    alpha_bbox = img_cpu.getchannel("A").getbbox()
    print(f"CPU map alpha non-zero bbox: {alpha_bbox}")

    # Check what is drawn on the map: are map tiles loaded or is it empty/transparent?
    # Count how many pixels have RGB != 0
    non_zero_rgb = np.sum(arr_cpu[:, :, :3] > 0)
    total_rgb = arr_cpu.shape[0] * arr_cpu.shape[1] * 3
    print(f"Non-zero RGB pixels: {non_zero_rgb} / {total_rgb} ({non_zero_rgb/total_rgb*100:.2f}%)")
    
    # Inspect the rows and columns
    # Find rows with non-zero alpha
    alpha_rows = np.where(arr_cpu[:, :, 3] > 0)[0]
    if len(alpha_rows) > 0:
        print(f"Alpha rows range: y_min={alpha_rows.min()}, y_max={alpha_rows.max()}, height={alpha_rows.max() - alpha_rows.min() + 1}")
    else:
        print("NO ALPHA PIXELS IN CPU MAP!")

if __name__ == "__main__":
    compare()
