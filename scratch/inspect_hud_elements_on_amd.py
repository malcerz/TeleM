from PIL import Image
import numpy as np

ref_hud = Image.open("scratch/reference_frame_150.png")
amd_full = Image.open("scratch/amd_frame_150.png")

# Calculate exact pixel positions from def_layout.json:
# canvas is 3840 x 2160, min_dim = 2160
# track_map: x=10.31%, y=35.8%, size=18%
map_cx = int(round(3840 * 0.1031))
map_cy = int(round(2160 * 0.358))
map_r = int(round(2160 * 0.18 / 2.0)) + 30
map_bbox = (max(0, map_cx - map_r), max(0, map_cy - map_r), min(3840, map_cx + map_r), min(2160, map_cy + map_r))

# lean_indicator: x=94.32%, y=16.58%, size=8%
lean_cx = int(round(3840 * 0.9432))
lean_cy = int(round(2160 * 0.1658))
lean_r = int(round(2160 * 0.08 / 2.0)) + 50
lean_bbox = (max(0, lean_cx - lean_r), max(0, lean_cy - lean_r), min(3840, lean_cx + lean_r), min(2160, lean_cy + lean_r))

# fit_distance_text (Horizontal bar): x=52.14%, y=9.16%
bar_cx = int(round(3840 * 0.5214))
bar_cy = int(round(2160 * 0.0916))
bar_bbox = (max(0, bar_cx - 1200), max(0, bar_cy - 150), min(3840, bar_cx + 1200), min(2160, bar_cy + 150))

# alt_text (Vertical bar): x=94.53%, y=48.11%
vert_cx = int(round(3840 * 0.9453))
vert_cy = int(round(2160 * 0.4811))
vert_bbox = (max(0, vert_cx - 200), max(0, vert_cy - 600), min(3840, vert_cx + 200), min(2160, vert_cy + 600))

print("=== EXACT BOUNDING BOXES ===")
print(f"  MAP:  {map_bbox} (center: {map_cx}, {map_cy})")
print(f"  LEAN: {lean_bbox} (center: {lean_cx}, {lean_cy})")
print(f"  BAR:  {bar_bbox} (center: {bar_cx}, {bar_cy})")
print(f"  VERT: {vert_bbox} (center: {vert_cx}, {vert_cy})")

# Extract and composite
for name, bbox in [("map", map_bbox), ("lean", lean_bbox), ("bar", bar_bbox), ("vert", vert_bbox)]:
    ref_crop = ref_hud.crop(bbox)
    amd_crop = amd_full.crop(bbox)
    
    # Save individual crops
    ref_crop.save(f"scratch/inspect_{name}_ref.png")
    amd_crop.save(f"scratch/inspect_{name}_amd.png")
    
    # Also create a composite of ref overlay over amd video frame for direct visual reference
    overlay_crop = amd_crop.copy()
    overlay_crop.paste(ref_crop, (0, 0), ref_crop)
    overlay_crop.save(f"scratch/inspect_{name}_expected_overlay.png")

print("Saved inspect_*_ref.png, inspect_*_amd.png, inspect_*_expected_overlay.png")
