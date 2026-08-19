"""Comprehensive analysis of ETAP 8J Fused Compositor vs Oracle."""
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
    print("=== PIXEL PARITY: ONE_PASS_REFERENCE vs CANDIDATE_FUSED (FINAL NV12) ===")
    print("==========================================================================")
    test_frames = [30, 225, 450, 675, 899]
    
    for f in test_frames:
        p_oracle = root / "scratch" / f"oracle_1pass_final_{f}.yuv"
        p_fused = root / "scratch" / f"fused_final_{f}.yuv"
        
        if not p_oracle.exists() or not p_fused.exists():
            print(f"Frame {f}: missing files ({p_oracle.exists()}, {p_fused.exists()})")
            continue
        
        y_orc, u_orc, v_orc = read_nv12(str(p_oracle))
        y_fus, u_fus, v_fus = read_nv12(str(p_fused))
        
        print(f"\n--- FRAME {f:3d} FULL-FRAME METRICS ---")
        for plane_name, p_orc, p_fus in [("Y (Luma)", y_orc, y_fus), ("U (Chroma)", u_orc, u_fus), ("V (Chroma)", v_orc, v_fus)]:
            diff = np.abs(p_fus.astype(np.int32) - p_orc.astype(np.int32))
            exact = np.mean(diff == 0) * 100.0
            within_1 = np.mean(diff <= 1) * 100.0
            within_2 = np.mean(diff <= 2) * 100.0
            mae = np.mean(diff)
            max_diff = np.max(diff)
            mse = np.mean(diff ** 2)
            psnr = 20 * np.log10(255.0 / np.sqrt(mse)) if mse > 0 else 999.0
            print(f"  {plane_name:12s} -> Exact: {exact:6.2f}%, Within ±1: {within_1:6.2f}%, Within ±2: {within_2:6.2f}%, MAE: {mae:5.3f}, MaxDiff: {max_diff:2d}, PSNR: {psnr:6.2f} dB")
            print(f"    ORACLE {plane_name:12s}: min={np.min(p_orc):3d}, max={np.max(p_orc):3d}, mean={np.mean(p_orc):6.2f}, med={np.median(p_orc):3.0f}")
            print(f"    FUSED  {plane_name:12s}: min={np.min(p_fus):3d}, max={np.max(p_fus):3d}, mean={np.mean(p_fus):6.2f}, med={np.median(p_fus):3.0f}")

        # Layer-specific region analysis on Frame 30
        if f == 30:
            print("\n  LAYER-SPECIFIC REGION PARITY (Frame 30):")
            # Define specific regions based on def_layout.json:
            # 1. Background (sky/asphalt where no widgets exist): (1000..1500, 1000..1500)
            # 2. Text (time text top left or speed text): (50..200, 50..400)
            # 3. Chart CAD/HR: (1000..1500, 100..1200)
            # 4. Speed Gauge: (1632..2280, 1544..2192)
            # 5. Map: (137..828, 3035..3726)
            # 6. ABOVE Layer: (936..998, 3300..3731)
            layers = {
                "Background Only (no HUD)": (slice(1000, 1500), slice(1000, 1500)),
                "Speed Gauge (Widget Bbox)": (slice(1632, 2160), slice(1544, 2192)),
                "Map (Widget Bbox)":         (slice(137, 828), slice(3035, 3726)),
                "Chart (Widget Bbox)":       (slice(1000, 1500), slice(100, 1200)),
                "ABOVE Layer (Widget Bbox)": (slice(936, 998), slice(3300, 3731)),
            }
            print(f"  {'Layer / Region':28s} | {'Exact Y %':10s} | {'Within ±1 Y %':14s} | {'MAE Y':8s} | {'MaxDiff Y':10s} | {'Exact UV %':10s}")
            print("  " + "-" * 90)
            for l_name, (sy, sx) in layers.items():
                ly_orc = y_orc[sy, sx]
                ly_fus = y_fus[sy, sx]
                ldiff_y = np.abs(ly_fus.astype(np.int32) - ly_orc.astype(np.int32))
                exact_y = np.mean(ldiff_y == 0) * 100.0
                within1_y = np.mean(ldiff_y <= 1) * 100.0
                mae_y = np.mean(ldiff_y)
                max_y = np.max(ldiff_y)

                # UV slice
                uv_sy = slice(sy.start // 2, sy.stop // 2)
                uv_sx = slice(sx.start // 2, sx.stop // 2)
                lu_orc, lu_fus = u_orc[uv_sy, uv_sx], u_fus[uv_sy, uv_sx]
                lv_orc, lv_fus = v_orc[uv_sy, uv_sx], v_fus[uv_sy, uv_sx]
                ldiff_uv = np.maximum(np.abs(lu_fus.astype(np.int32) - lu_orc.astype(np.int32)),
                                      np.abs(lv_fus.astype(np.int32) - lv_orc.astype(np.int32)))
                exact_uv = np.mean(ldiff_uv == 0) * 100.0
                print(f"  {l_name:28s} | {exact_y:8.2f} % | {within1_y:12.2f} % | {mae_y:7.3f} | {max_y:9d} | {exact_uv:8.2f} %")


def parse_gpu_timings():
    print("\n==========================================================================")
    print("=== ETAP 8J GPU TIMINGS 3 × 900 (MEDIAN / P95 / P99 MS) ===")
    print("==========================================================================")
    target_files = [
        ("ONE_PASS_REFERENCE (Old)", "etap8j_oracle_1pass.mp4.gpu_timeline.csv"),
        ("CANDIDATE_FUSED Run 1",   "etap8j_fused_run1.mp4.gpu_timeline.csv"),
        ("CANDIDATE_FUSED Run 2",   "etap8j_fused_run2.mp4.gpu_timeline.csv"),
        ("CANDIDATE_FUSED Run 3",   "etap8j_fused_run3.mp4.gpu_timeline.csv"),
    ]
    print(f"{'Run / Wariant':26s} | {'GPU Span':16s} | {'VideoProc Blt':16s} | {'Range Normalize':16s} | {'Map Resample+Bld':16s} | {'HUD/Fused CS':16s}")
    print("-" * 125)
    for title, tf in target_files:
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
        print(f"{title:26s} | {np.median(span):5.2f}/{np.percentile(span,95):5.2f}/{np.percentile(span,99):5.2f} | {np.median(vp):5.2f}/{np.percentile(vp,95):5.2f}/{np.percentile(vp,99):5.2f} | {np.median(rng):5.2f}/{np.percentile(rng,95):5.2f}/{np.percentile(rng,99):5.2f} | {np.median(m_cs):5.2f}/{np.percentile(m_cs,95):5.2f}/{np.percentile(m_cs,99):5.2f} | {np.median(hud):5.2f}/{np.percentile(hud,95):5.2f}/{np.percentile(hud,99):5.2f}")


if __name__ == "__main__":
    analyze_pixel_parity()
    parse_gpu_timings()
