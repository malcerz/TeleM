"""ETAP 8H: In-depth diagnostic runner and mathematical audit of NormalizeD3D11VARangeNV12."""
import copy
import json
import math
import os
import sys
import time
from pathlib import Path
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    interpolate_value,
    load_json_with_fallback,
    smooth_speed_samples,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

# Setup common environment
os.environ["AMD_NATIVE_D3D11"] = "1"
os.environ["AMD_NATIVE_DECODE"] = "D3D11VA"
os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
os.environ["AMD_FRAME_ACCOUNTING"] = "1"
os.environ["AMD_NATIVE_FRAME_ACCOUNTING"] = "1"
os.environ["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
os.environ["AMD_AMF_DIAG"] = "1"
os.environ["AMD_CHART_PATH"] = "GPU_SPLIT"
os.environ["AMD_GAUGE_PATH"] = "GPU"
os.environ["AMD_MAP_PATH"] = "GPU"
os.environ["AMD_OVERLAY_PROFILE"] = "0"

records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX030120.json"))
tm = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
)
tm.load_gpmf_records(records)
tm.load_fit(root / "Video" / "Poranna_jazda_na_rowerze.fit")
tm.start_dt_utc = tm.speed_samples[0][0]

layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
alt = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
track = tm.track_samples


def run_export_pass(tag: str, frames: int = 900, env_overrides: dict = None):
    print(f"\n=======================================================")
    print(f"=== RUNNING EXPORT: {tag} ({frames} frames) ===")
    print(f"=======================================================")
    if env_overrides:
        os.environ.update(env_overrides)
    
    out_mp4 = root / "scratch" / f"{tag}.mp4"
    if out_mp4.exists():
        try: out_mp4.unlink()
        except: pass

    duration = frames * (1001 / 30000)
    t0 = time.perf_counter()
    res = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(root / "Video" / "GX030120.MP4")],
        output_file=str(out_mp4),
        duration_s=duration,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=0.0,
        speed_samples=speed,
        track_samples=track,
        alt_samples=alt,
        field_samples={"speed_samples": speed, "track_samples": track, "alt_samples": alt},
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        layout=layout,
        font_path="arial.ttf",
        encoder="amd_native",
    )
    t1 = time.perf_counter()
    print(f"Export {tag} completed in {t1-t0:.2f}s, res={res}")
    
    prof_json = out_mp4.with_name(out_mp4.name + ".amd_profile.json")
    pdata = json.load(open(prof_json)) if prof_json.exists() else {}
    return pdata


def parse_gpu_timestamps(prof_data):
    ts = prof_data.get("gpu_timestamps", {})
    results = {}
    for k in ["span_ms", "vp_ms", "range_ms", "map_ms", "hud_ms", "charts_ms", "gauge_ms"]:
        if k in ts:
            results[k] = ts[k]
    return results


def read_nv12(yuv_path: str, width: int = 3840, height: int = 2160):
    raw = open(yuv_path, "rb").read()
    y_size = width * height
    uv_size = width * height // 2
    if len(raw) < y_size + uv_size:
        raise ValueError(f"File {yuv_path} too small: {len(raw)} vs {y_size + uv_size}")
    
    y_plane = np.frombuffer(raw[:y_size], dtype=np.uint8).reshape((height, width))
    uv_raw = np.frombuffer(raw[y_size:y_size + uv_size], dtype=np.uint8).reshape((height // 2, width // 2, 2))
    u_plane = uv_raw[:, :, 0]
    v_plane = uv_raw[:, :, 1]
    return y_plane, u_plane, v_plane


def analyze_sampled_frames():
    print(f"\n=======================================================")
    print(f"=== ANALYZING SAMPLED YUV FRAMES (PRE vs POST NORMALIZE) ===")
    print(f"=======================================================")
    
    sample_frames = [30, 225, 450, 675, 899]
    
    for f in sample_frames:
        p_raw = root / "scratch" / f"diag_vp_raw_frame_{f}.yuv"
        p_norm = root / "scratch" / f"diag_post_norm_frame_{f}.yuv"
        
        if not p_raw.exists() or not p_norm.exists():
            print(f"Frame {f}: raw or norm file missing!")
            continue
        
        y_raw, u_raw, v_raw = read_nv12(str(p_raw))
        y_norm, u_norm, v_norm = read_nv12(str(p_norm))
        
        print(f"\n--- FRAME {f:3d} STATISTICAL PROFILE ---")
        print(f"  PLANE Y (Raw VP output):    min={np.min(y_raw):3d}, max={np.max(y_raw):3d}, mean={np.mean(y_raw):6.2f}, med={np.median(y_raw):3.0f}, p01={np.percentile(y_raw, 1):3.0f}, p99={np.percentile(y_raw, 99):3.0f}")
        print(f"  PLANE Y (Post Normalize):  min={np.min(y_norm):3d}, max={np.max(y_norm):3d}, mean={np.mean(y_norm):6.2f}, med={np.median(y_norm):3.0f}, p01={np.percentile(y_norm, 1):3.0f}, p99={np.percentile(y_norm, 99):3.0f}")
        print(f"  PLANE U (Raw VP output):    min={np.min(u_raw):3d}, max={np.max(u_raw):3d}, mean={np.mean(u_raw):6.2f}, med={np.median(u_raw):3.0f}")
        print(f"  PLANE U (Post Normalize):  min={np.min(u_norm):3d}, max={np.max(u_norm):3d}, mean={np.mean(u_norm):6.2f}, med={np.median(u_norm):3.0f}")
        print(f"  PLANE V (Raw VP output):    min={np.min(v_raw):3d}, max={np.max(v_raw):3d}, mean={np.mean(v_raw):6.2f}, med={np.median(v_raw):3.0f}")
        print(f"  PLANE V (Post Normalize):  min={np.min(v_norm):3d}, max={np.max(v_norm):3d}, mean={np.mean(v_norm):6.2f}, med={np.median(v_norm):3.0f}")

        # Mathematical verification: test CPU formula vs GPU output on full frame
        from scratch.test_range_normalize_audit import pass2_y, pass2_uv
        cpu_y = np.vectorize(pass2_y)(y_raw)
        diff_y = np.abs(y_norm.astype(np.int32) - cpu_y.astype(np.int32))
        exact_match_y = np.mean(diff_y == 0) * 100.0
        within_1_y = np.mean(diff_y <= 1) * 100.0
        max_diff_y = np.max(diff_y)
        print(f"  CPU Formula vs GPU Output Y: Exact Matches={exact_match_y:.2f}%, Within ±1={within_1_y:.2f}%, Max Diff={max_diff_y}")

        # Region samples (very dark, midtone, bright sky, white highlight, neutral gray)
        # We can find coordinates for these regions from frame 30
        h, w = y_raw.shape
        regions = {
            "Dark Shadow": (int(h * 0.8), int(w * 0.2)),
            "Midtone Asphalt": (int(h * 0.7), int(w * 0.5)),
            "Bright Sky": (int(h * 0.1), int(w * 0.5)),
            "White Highlight": (int(h * 0.15), int(w * 0.8)),
            "Neutral Gray": (int(h * 0.5), int(w * 0.1)),
        }
        print("  Specific Region Samples (5x5 avg):")
        for r_name, (cy, cx) in regions.items():
            r_y_raw = np.mean(y_raw[cy-2:cy+3, cx-2:cx+3])
            r_y_norm = np.mean(y_norm[cy-2:cy+3, cx-2:cx+3])
            r_u_raw = np.mean(u_raw[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
            r_u_norm = np.mean(u_norm[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
            r_v_raw = np.mean(v_raw[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
            r_v_norm = np.mean(v_norm[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
            print(f"    {r_name:16s}: Y raw={r_y_raw:5.1f} -> norm={r_y_norm:5.1f} | U raw={r_u_raw:5.1f} -> norm={r_u_norm:5.1f} | V raw={r_v_raw:5.1f} -> norm={r_v_norm:5.1f}")


if __name__ == "__main__":
    # 1. First run with frame dumps to collect raw frames
    os.environ["AMD_NORMALIZE_PASSES"] = "2"
    os.environ["AMD_DUMP_RANGE_FRAMES"] = "0,30,225,450,675,899"
    p_base1 = run_export_pass("8h_baseline_run1", 900)
    
    # 2. Run 2 more baseline passes for 3x900 stats
    os.environ["AMD_DUMP_RANGE_FRAMES"] = ""
    p_base2 = run_export_pass("8h_baseline_run2", 900)
    p_base3 = run_export_pass("8h_baseline_run3", 900)

    # 3. Analyze sampled frames
    analyze_sampled_frames()

    # 4. Ablation A/B tests:
    # Option B: Single pass (AMD_NORMALIZE_PASSES=1)
    p_pass1 = run_export_pass("8h_ablation_pass1", 900, {"AMD_NORMALIZE_PASSES": "1"})

    # Option C: Bypass (AMD_NORMALIZE_PASSES=0)
    p_pass0 = run_export_pass("8h_ablation_bypass", 900, {"AMD_NORMALIZE_PASSES": "0"})

    # Option D: VP Nominal Range test (AMD_VP_NOMINAL_IN=2, AMD_VP_NOMINAL_OUT=1, AMD_NORMALIZE_PASSES=0)
    p_vp_nom = run_export_pass("8h_ablation_vp_nominal", 900, {
        "AMD_VP_NOMINAL_IN": "2",
        "AMD_VP_NOMINAL_OUT": "1",
        "AMD_NORMALIZE_PASSES": "0"
    })

    print("\n=======================================================")
    print("=== SUMMARY OF GPU TIMINGS (MEDIAN MS ACROSS RUNS) ===")
    print("=======================================================")
    runs = {
        "Baseline Run 1 (2 passes)": p_base1,
        "Baseline Run 2 (2 passes)": p_base2,
        "Baseline Run 3 (2 passes)": p_base3,
        "Ablation 1 Pass": p_pass1,
        "Ablation Bypass (0 passes)": p_pass0,
        "Ablation VP Nominal Range": p_vp_nom,
    }
    print(f"{'Run':30s} | {'GPU Span':10s} | {'VP Blt':10s} | {'Range CS':10s} | {'Map CS':10s} | {'HUD CS':10s}")
    print("-" * 90)
    for r_name, pdata in runs.items():
        ts = parse_gpu_timestamps(pdata)
        span = ts.get("span_ms", {}).get("median_ms", 0.0)
        vp = ts.get("vp_ms", {}).get("median_ms", 0.0)
        rng = ts.get("range_ms", {}).get("median_ms", 0.0)
        m_cs = ts.get("map_ms", {}).get("median_ms", 0.0)
        hud = ts.get("hud_ms", {}).get("median_ms", 0.0)
        print(f"{r_name:30s} | {span:8.3f} ms | {vp:8.3f} ms | {rng:8.3f} ms | {m_cs:8.3f} ms | {hud:8.3f} ms")
