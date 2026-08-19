"""
Crop the bottom section of chart images to examine clipping precisely.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

root = Path("c:/_DEV/TeleM")
out_dir = root / "Raporty/etap8m7_artifacts"

resolutions = ["4K", "1080p", "720p", "480p"]

for res_name in resolutions:
    img_path = out_dir / f"chart_preview_{res_name}.png"
    img = Image.open(str(img_path))
    w, h = img.size
    
    # Crop bottom 120px (or full image if smaller)
    crop_h = min(120, h)
    crop = img.crop((0, h - crop_h, w, h))
    
    # Scale up 2x for visibility
    crop_big = crop.resize((w * 2, crop_h * 2), Image.NEAREST)
    
    # Draw a green line at pixel y = original_h - orig_h (i.e., last frame pixel)
    draw = ImageDraw.Draw(crop_big)
    # The red line is at the very bottom of the crop
    
    out_path = out_dir / f"chart_bottom_crop_{res_name}.png"
    crop_big.save(str(out_path))
    print(f"{res_name}: crop saved {out_path}")
    print(f"  full img size: {w}x{h}")
    print(f"  crop height: {crop_h}px of original")
