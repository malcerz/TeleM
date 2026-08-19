"""Inspect what indicators appear on scratch/frame_30_output_h265.png."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")

def inspect_frame():
    p = root / "scratch" / "frame_30_output_h265.png"
    img = Image.open(p)
    w, h = img.size
    print(f"Frame size: {w}x{h}")
    
    # Check top-left (time_block region: x=0..200, y=0..100)
    # Check mid-left (ISO/Ext/TGP region: x=0..150, y=180..260)
    # Check bottom-center (Speed/Gauge region: x=350..500, y=350..450)
    # Check bottom-right (Map region: x=650..850, y=300..480)
    
    tl = img.crop((0, 0, int(w*0.25), int(h*0.25)))
    ml = img.crop((0, int(h*0.35), int(w*0.25), int(h*0.6)))
    bc = img.crop((int(w*0.35), int(h*0.65), int(w*0.65), h))
    br = img.crop((int(w*0.7), int(h*0.65), w, h))
    
    tl.save(root / "scratch" / "crop_tl_time_block.png")
    ml.save(root / "scratch" / "crop_ml_iso_ext_tgp.png")
    bc.save(root / "scratch" / "crop_bc_gauge.png")
    br.save(root / "scratch" / "crop_br_map.png")
    
    print("Saved crops of all 4 indicator areas.")

if __name__ == "__main__":
    inspect_frame()
