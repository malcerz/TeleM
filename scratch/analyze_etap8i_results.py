"""Analyze pixel parity and GPU performance for ETAP 8I."""
import csv
import glob
from pathlib import Path
import numpy as np

root = Path("c:/_DEV/TeleM")

def read_nv12(yuv_path: str, width: int = 3840, height: int = 2160):
    raw = open(yuv_path, "rb").read()
    y_size = width * height
    uv_size = width * height // 2
    y_plane = np.frombuffer(raw[:y_size], dtype=np.uint8).reshape((height, width))
    uv_raw = np.frombuffer(raw[y_size:y_size + uv_size], dtype=np.uint8).reshape((height // 2, width // 2, 2))
    u_plane = uv_raw[:, :, 0]
    v_plane = uv_raw[:, :, 1]
    return y_plane, u_plane, v_plane

def analyze_pixel_parity():
    print("==========================================================================")
    print("=== PIXEL PARITY: ONE_PASS_REFERENCE vs NEW_VP_LIMITED_ZERO_PASS (Y, U, V) ===")
    print("==========================================================================")
    test_frames = [30, 225, 450, 675, 899]
    
    for f in test_frames:
        p_oracle = root / "scratch" / f"oracle_1pass_frame_{f}.yuv"
        p_new_vp = root / "scratch" / f"new_vp_limited_frame_{f}.yuv"
        
        if not p_oracle.exists() or not p_new_vp.exists():
            print(f"Frame {f}: missing files ({p_oracle.exists()}, {p_new_vp.exists()})")
            continue
        
        y_orc, u_orc, v_orc = read_nv12(str(p_oracle))
        y_new, u_new, v_new = read_nv12(str(p_new_vp))
        
        print(f"\n--- FRAME {f:3d} ---")
        for plane_name, p_orc, p_new in [("Y (Luma)", y_orc, y_new), ("U (Chroma)", u_orc, u_new), ("V (Chroma)", v_orc, v_new)]:
            diff = np.abs(p_new.astype(np.int32) - p_orc.astype(np.int32))
            exact = np.mean(diff == 0) * 100.0
            within_1 = np.mean(diff <= 1) * 100.0
            within_2 = np.mean(diff <= 2) * 100.0
            mae = np.mean(diff)
            max_diff = np.max(diff)
            print(f"  {plane_name:12s} -> Exact: {exact:6.2f}%, Within ±1: {within_1:6.2f}%, Within ±2: {within_2:6.2f}%, MAE: {mae:5.3f}, MaxDiff: {max_diff}")
            print(f"    ORACLE {plane_name:12s}: min={np.min(p_orc):3d}, max={np.max(p_orc):3d}, mean={np.mean(p_orc):6.2f}, med={np.median(p_orc):3.0f}, p01={np.percentile(p_orc,1):3.0f}, p99={np.percentile(p_orc,99):3.0f}")
            print(f"    NEW VP {plane_name:12s}: min={np.min(p_new):3d}, max={np.max(p_new):3d}, mean={np.mean(p_new):6.2f}, med={np.median(p_new):3.0f}, p01={np.percentile(p_new,1):3.0f}, p99={np.percentile(p_new,99):3.0f}")

        # Characteristic regions on Frame 30
        if f == 30:
            h, w = y_orc.shape
            regions = {
                "Dark Shadow": (int(h * 0.8), int(w * 0.2)),
                "Midtone Asphalt": (int(h * 0.7), int(w * 0.5)),
                "Bright Sky": (int(h * 0.1), int(w * 0.5)),
                "White Highlight": (int(h * 0.15), int(w * 0.8)),
                "Neutral Gray": (int(h * 0.5), int(w * 0.1)),
            }
            print("\n  Characteristic Regions Comparison (5x5 avg):")
            print(f"  {'Region':18s} | {'Oracle Y':9s} | {'New VP Y':9s} | {'Oracle U':9s} | {'New VP U':9s} | {'Oracle V':9s} | {'New VP V':9s}")
            print("  " + "-" * 75)
            for r_name, (cy, cx) in regions.items():
                oy = np.mean(y_orc[cy-2:cy+3, cx-2:cx+3])
                ny = np.mean(y_new[cy-2:cy+3, cx-2:cx+3])
                ou = np.mean(u_orc[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
                nu = np.mean(u_new[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
                ov = np.mean(v_orc[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
                nv = np.mean(v_new[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
                print(f"  {r_name:18s} | {oy:9.1f} | {ny:9.1f} | {ou:9.1f} | {nu:9.1f} | {ov:9.1f} | {nv:9.1f}")


def parse_gpu_timings():
    print("\n==========================================================================")
    print("=== ETAP 8I GPU TIMINGS 3 × 900 (MEDIAN / P95 / P99 MS) ===")
    print("==========================================================================")
    target_files = [
        "etap8i_oracle_1pass.mp4.gpu_timeline.csv",
        "etap8i_new_vp_limited_run1.mp4.gpu_timeline.csv",
        "etap8i_new_vp_limited_run2.mp4.gpu_timeline.csv",
        "etap8i_new_vp_limited_run3.mp4.gpu_timeline.csv",
    ]
    print(f"{'Run / File':32s} | {'GPU Span':16s} | {'VideoProc Blt':16s} | {'Range Normalize':16s} | {'Map Resample+Bld':16s} | {'HUD Direct NV12':16s}")
    print("-" * 125)
    for tf in target_files:
        p = root / "scratch" / tf
        if not p.exists():
            continue
        rows = list(csv.DictReader(open(p)))
        if not rows:
            continue
        span = [float(r["span_ms"]) for r in rows]
        vp = [float(r["vp_ms"]) for r in rows]
        rng = [float(r["range_ms"]) for r in rows]
        m_cs = [float(r["map_ms"]) for r in rows]
        hud = [float(r["hud_ms"]) for r in rows]
        name = tf.replace(".mp4.gpu_timeline.csv", "")
        print(f"{name:32s} | {np.median(span):5.2f}/{np.percentile(span,95):5.2f}/{np.percentile(span,99):5.2f} | {np.median(vp):5.2f}/{np.percentile(vp,95):5.2f}/{np.percentile(vp,99):5.2f} | {np.median(rng):5.2f}/{np.percentile(rng,95):5.2f}/{np.percentile(rng,99):5.2f} | {np.median(m_cs):5.2f}/{np.percentile(m_cs,95):5.2f}/{np.percentile(m_cs,99):5.2f} | {np.median(hud):5.2f}/{np.percentile(hud,95):5.2f}/{np.percentile(hud,99):5.2f}")


if __name__ == "__main__":
    analyze_pixel_parity()
    parse_gpu_timings()
