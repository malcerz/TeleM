"""Analyze what is rendered at map location in frame_0030.png."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
vid_p = root / "scratch" / "gui_export_inspection" / "vid_dst_bbox_crop.png"
cpu_p = root / "scratch" / "gui_export_inspection" / "cpu_working_map.png"

def analyze():
    img_vid = Image.open(vid_p)
    img_cpu = Image.open(cpu_p).resize((691, 691))
    
    arr_vid = np.array(img_vid)
    arr_cpu = np.array(img_cpu)
    
    # Save side-by-side comparison
    side_by_side = Image.new("RGB", (691 * 2, 691))
    side_by_side.paste(img_vid, (0, 0))
    side_by_side.paste(img_cpu.convert("RGB"), (691, 0))
    side_by_side.save(root / "scratch" / "gui_export_inspection" / "map_side_by_side.png")
    print("Saved map_side_by_side.png!")

    # Check difference between CPU map and Video crop
    diff = np.abs(arr_vid.astype(np.int32) - arr_cpu[:, :, :3].astype(np.int32))
    print(f"Diff stats: min={diff.min()}, max={diff.max()}, mean={diff.mean():.2f}")
    
    # Check if video crop actually contains the background video with map blended over it, or something else!
    # Let's check how the map looks visually:
    # Does the map have satellite tiles, or is it just the red GPS track line on black?
    # Let's check color channels:
    print(f"Video crop mean per channel R={arr_vid[:,:,0].mean():.1f}, G={arr_vid[:,:,1].mean():.1f}, B={arr_vid[:,:,2].mean():.1f}")
    print(f"CPU map mean per channel R={arr_cpu[:,:,0].mean():.1f}, G={arr_cpu[:,:,1].mean():.1f}, B={arr_cpu[:,:,2].mean():.1f}")

if __name__ == "__main__":
    analyze()
