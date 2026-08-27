import math
import subprocess
import numpy as np
from pathlib import Path
from PIL import Image

OUT_DIR = Path("scratch/etap1c_test")
FRAMES_DIR = OUT_DIR / "parity_frames"
MP4_A = OUT_DIR / "mode_a_baseline_300f.mp4"
MP4_B = OUT_DIR / "mode_b_gpu_map_only_300f.mp4"
MP4_C = OUT_DIR / "mode_c_combined_300f.mp4"

def extract_frame(mp4_path: Path, frame_idx: int, out_png: Path):
    cmd = [
        "ffmpeg", "-y", "-i", str(mp4_path),
        "-vf", f"select=eq(n\\,{frame_idx})",
        "-vframes", "1",
        str(out_png)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def calc_metrics(a1, a2):
    diff = np.abs(a1.astype(np.float32) - a2.astype(np.float32))
    max_d = float(np.max(diff))
    mae = float(np.mean(diff))
    mse = float(np.mean((a1.astype(np.float32) - a2.astype(np.float32)) ** 2))
    psnr = 100.0 if mse == 0 else 20 * math.log10(255.0 / math.sqrt(mse))
    diff_pixels = int(np.sum(np.any(diff > 0, axis=-1)))
    total_pixels = a1.shape[0] * a1.shape[1]
    return {
        "max_diff": max_d, "mae": mae, "psnr": psnr,
        "diff_pct": diff_pixels / total_pixels * 100.0
    }

def main():
    frames = [0, 10, 30, 60, 120, 240]
    
    # ROIs in 3840x2160:
    # Map bbox: (2880, 260, 2880 + 691, 260 + 691)
    map_roi = (2880, 260, 2880 + 691, 260 + 691)
    # Cadence Chart bbox: x=27%, y=82%, w=30%, h=21.5% -> (1036 - 580, 1771 - 233, 1160, 466) = (456, 1538, 456 + 1160, 1538 + 466)
    # Let's crop Cadence ROI: (400, 1500, 1600, 2050)
    cadence_roi = (400, 1500, 1600, 2050)
    # HR Chart bbox: x=73%, y=82% -> (2803 - 580, 1771 - 233, 1160, 466) = (2223, 1538, 2223 + 1160, 1538 + 466)
    # HR ROI: (2200, 1500, 3400, 2050)
    hr_roi = (2200, 1500, 3400, 2050)
    # Dist / HR Overlap ROI (dist_visual is at y=74% = 1600, x=50%, w=60% = 2304 -> x=768..3072, y=1550..1650)
    # Overlap with HR chart: (2223, 1550, 3072, 1650)
    overlap_roi = (2223, 1550, 3072, 1650)

    print("=========================================================================================")
    print("ETAP 1C: VISUAL / PARITY COMPARISON (Mode A Baseline vs Mode C Combined GPU)")
    print("=========================================================================================")
    
    for f in frames:
        png_a = FRAMES_DIR / f"frame_{f:04d}_mode_a.png"
        png_c = FRAMES_DIR / f"frame_{f:04d}_mode_c.png"
        
        extract_frame(MP4_A, f, png_a)
        extract_frame(MP4_C, f, png_c)
        
        im_a = Image.open(png_a).convert("RGBA")
        im_c = Image.open(png_c).convert("RGBA")
        
        arr_a = np.array(im_a)
        arr_c = np.array(im_c)
        
        m_full = calc_metrics(arr_a, arr_c)
        m_map = calc_metrics(np.array(im_a.crop(map_roi)), np.array(im_c.crop(map_roi)))
        m_cad = calc_metrics(np.array(im_a.crop(cadence_roi)), np.array(im_c.crop(cadence_roi)))
        m_hr = calc_metrics(np.array(im_a.crop(hr_roi)), np.array(im_c.crop(hr_roi)))
        m_ovlp = calc_metrics(np.array(im_a.crop(overlap_roi)), np.array(im_c.crop(overlap_roi)))
        
        print(f"\n--- FRAME {f:04d} ---")
        print(f"  Full 4K Frame:     MAE = {m_full['mae']:6.3f} | PSNR = {m_full['psnr']:5.2f} dB | Diff Px = {m_full['diff_pct']:5.2f}% | Max Diff = {m_full['max_diff']}")
        print(f"  Map ROI:           MAE = {m_map['mae']:6.3f} | PSNR = {m_map['psnr']:5.2f} dB | Diff Px = {m_map['diff_pct']:5.2f}% | Max Diff = {m_map['max_diff']}")
        print(f"  Cadence Chart ROI: MAE = {m_cad['mae']:6.3f} | PSNR = {m_cad['psnr']:5.2f} dB | Diff Px = {m_cad['diff_pct']:5.2f}% | Max Diff = {m_cad['max_diff']}")
        print(f"  HR Chart ROI:      MAE = {m_hr['mae']:6.3f} | PSNR = {m_hr['psnr']:5.2f} dB | Diff Px = {m_hr['diff_pct']:5.2f}% | Max Diff = {m_hr['max_diff']}")
        print(f"  Dist/HR Overlap:   MAE = {m_ovlp['mae']:6.3f} | PSNR = {m_ovlp['psnr']:5.2f} dB | Diff Px = {m_ovlp['diff_pct']:5.2f}% | Max Diff = {m_ovlp['max_diff']}")

if __name__ == "__main__":
    main()
