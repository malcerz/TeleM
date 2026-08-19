"""Compare frame orientations across 4K, 1080p, and 720p."""
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")

def check_orientation():
    ref_auto = Image.open(root / "scratch" / "rotation_diag" / "raw_ffmpeg_autorotated.png")
    ref_noauto = Image.open(root / "scratch" / "rotation_diag" / "raw_ffmpeg_noautorotate.png")
    
    f4k = Image.open(root / "scratch" / "validation_exports" / "frame_30_4k.png")
    f1080p = Image.open(root / "scratch" / "validation_exports" / "frame_30_1080p.png")
    f720p = Image.open(root / "scratch" / "validation_exports" / "frame_30_720p.png")
    
    w_ref, h_ref = ref_auto.size
    c_ref_auto = ref_auto.crop((w_ref//4, h_ref//4, 3*w_ref//4, 3*h_ref//4))
    c_ref_noauto = ref_noauto.crop((w_ref//4, h_ref//4, 3*w_ref//4, 3*h_ref//4))
    
    a_auto = np.array(c_ref_auto.resize((500, 500), Image.Resampling.BILINEAR))[:, :, :3]
    a_noauto = np.array(c_ref_noauto.resize((500, 500), Image.Resampling.BILINEAR))[:, :, :3]
    
    for label, img in [("4K", f4k), ("1080p", f1080p), ("720p", f720p)]:
        w, h = img.size
        c = img.crop((w//4, h//4, 3*w//4, 3*h//4))
        a = np.array(c.resize((500, 500), Image.Resampling.BILINEAR))[:, :, :3]
        
        mae_auto = np.mean(np.abs(a.astype(float) - a_auto.astype(float)))
        mae_noauto = np.mean(np.abs(a.astype(float) - a_noauto.astype(float)))
        
        print(f"[{label:5s}] vs FFmpeg autorotated (correct):    MAE = {mae_auto:.2f} -> {'PASS' if mae_auto < 15 else 'FAIL'}")
        print(f"[{label:5s}] vs FFmpeg unrotated (upside down): MAE = {mae_noauto:.2f}")

if __name__ == "__main__":
    check_orientation()
