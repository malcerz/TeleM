"""Analyze user export frame_30_output_h265.png for all indicator texts."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")

def analyze():
    p = root / "scratch" / "frame_30_output_h265.png"
    img = Image.open(p)
    arr = np.array(img)
    w, h = img.size
    print(f"Frame dimensions: {w}x{h}")
    
    # Let's inspect where text indicators should be:
    # 1. time_block: x = 1.6139% = 13.8 px, y = 3.1024% = 14.9 px
    # 2. iso_text: x = 1.74% = 14.8 px, y = 41.71% = 200.2 px
    # 3. exposure_text: x = 1.69% = 14.4 px, y = 45.63% = 219.0 px
    # 4. temp_text: x = 1.65% = 14.1 px, y = 49.48% = 237.5 px
    
    print("\nChecking regions for white/text pixels (R>200, G>200, B>200):")
    # Region 1: Top-Left (time_block) [0:100, 0:200]
    tb_region = arr[0:100, 0:200]
    white_tb = np.sum((tb_region[:, :, 0] > 200) & (tb_region[:, :, 1] > 200) & (tb_region[:, :, 2] > 200))
    print(f"  time_block area white pixels: {white_tb}")
    
    # Region 2: Mid-Left (iso, exp, temp) [180:270, 0:200]
    gpmf_region = arr[180:270, 0:200]
    white_gpmf = np.sum((gpmf_region[:, :, 0] > 200) & (gpmf_region[:, :, 1] > 200) & (gpmf_region[:, :, 2] > 200))
    print(f"  GPMF text area white pixels: {white_gpmf}")
    
    # Region 3: Center-Bottom (gauge) [300:480, 250:600]
    gauge_region = arr[300:480, 250:600]
    white_gauge = np.sum((gauge_region[:, :, 0] > 200) & (gauge_region[:, :, 1] > 200) & (gauge_region[:, :, 2] > 200))
    print(f"  Gauge area white pixels: {white_gauge}")
    
    # Region 4: Bottom-Right (map) [250:480, 600:854]
    map_region = arr[250:480, 600:854]
    white_map = np.sum((map_region[:, :, 0] > 200) & (map_region[:, :, 1] > 200) & (map_region[:, :, 2] > 200))
    print(f"  Map area white pixels: {white_map}")

if __name__ == "__main__":
    analyze()
