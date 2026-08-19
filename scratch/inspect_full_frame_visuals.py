"""Inspect all elements on frame_0030.png."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
f30_path = root / "scratch" / "gui_export_inspection" / "frame_0030.png"

def inspect_visuals():
    img = Image.open(f30_path)
    print(f"Full frame size: {img.size}")
    
    # Save smaller thumbnail of full frame
    thumb = img.resize((960, 540))
    thumb.save(root / "scratch" / "gui_export_inspection" / "frame_0030_thumb.png")
    print("Saved frame_0030_thumb.png!")

    # Check top-right region where map is located:
    # dst_bbox = (3035, 137, 691, 691)
    # What about the map shape or map rendering?
    # In def_layout.json:
    # "zoom": 14, "map_style": "satellite", "direction": "horizontal", "grow_height": false ...
    # Wait! Look at def_layout.json for track_map:
    # Does def_layout.json have "direction": "horizontal", "grow_height": false, "segments": 30, "segment_gap": 3 ...?
    # Those are BAR indicator parameters mixed into track_map!
    # But what about map_shape? In def_layout.json: there is NO "map_shape" key!
    
    # Let's inspect the actual pixels inside the map region in the thumbnail / frame:
    map_region = img.crop((3035, 137, 3035 + 691, 137 + 691))
    map_region.save(root / "scratch" / "gui_export_inspection" / "map_region_exact.png")
    
    # Check if there is another map element or bar element rendered on top of it, or if GPU map blend happened!
    # In GPU mode, amd_native_exporter.py executes:
    # 1. CPU_BELOW_MAP
    # 2. ResampleAndBlendMap (native GPU)
    # 3. CPU_ABOVE_MAP (above_map_img blended)
    # Let's check what was uploaded to the native GPU for the map!

if __name__ == "__main__":
    inspect_visuals()
