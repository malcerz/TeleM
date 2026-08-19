"""Compare 03_map_upload_source.png with the actual map in output_h265.mp4."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
upload_p = root / "scratch" / "etap8m_diag" / "03_map_upload_source.png"
vid_p = root / "scratch" / "gui_export_inspection" / "map_crop_0030.png"

def check():
    img_up = Image.open(upload_p)
    img_vid = Image.open(vid_p)
    print(f"Upload source size: {img_up.size}, mode={img_up.mode}")
    print(f"Video map crop size: {img_vid.size}, mode={img_vid.mode}")
    
    # Save a comparison image
    # In Video/output_h265.mp4, where was the map blended?
    # Bbox in 4K: dst_bbox = (3035, 137, 691, 691).
    # map_crop_0030.png was cropped from (3000, 100, 3800, 900) (size 800x800).
    # Let's crop exact (3035, 137, 3035+691, 137+691) from frame_0030.png!
    f30_p = root / "scratch" / "gui_export_inspection" / "frame_0030.png"
    if f30_p.exists():
        f30 = Image.open(f30_p)
        exact_vid_map = f30.crop((3035, 137, 3035 + 691, 137 + 691))
        exact_vid_map.save(root / "scratch" / "etap8m_diag" / "05_final_frame_map.png")
        
        # Check non-zero differences
        arr_up = np.array(img_up.resize((691, 691)))
        arr_vid = np.array(exact_vid_map)
        
        print(f"Upload source Alpha stats: min={arr_up[:,:,3].min()}, max={arr_up[:,:,3].max()}, mean={arr_up[:,:,3].mean():.2f}")
        print(f"Upload source RGB stats: min={arr_up[:,:,:3].min()}, max={arr_up[:,:,:3].max()}, mean={arr_up[:,:,:3].mean():.2f}")
        print(f"Video crop RGB stats: min={arr_vid.min()}, max={arr_vid.max()}, mean={arr_vid.mean():.2f}")

if __name__ == "__main__":
    check()
