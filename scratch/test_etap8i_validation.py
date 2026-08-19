"""Comprehensive validation and benchmarking suite for ETAP 8I."""
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

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

def run_single_process(name: str, env_vars: dict, frames: int = 900):
    print(f"\n=======================================================")
    print(f"=== RUNNING RUN: {name} ({frames} frames) ===")
    print(f"=======================================================")
    env_str = "\n".join([f"os.environ['{k}'] = '{v}'" for k, v in env_vars.items()])
    script = f"""
import os, sys, json
from pathlib import Path
root = Path('c:/_DEV/TeleM')
sys.path.insert(0, str(root))
os.environ['AMD_NATIVE_D3D11'] = '1'
os.environ['AMD_NATIVE_DECODE'] = 'D3D11VA'
os.environ['AMD_NATIVE_HUD_MODE'] = 'GPU_HUD'
os.environ['AMD_FRAME_ACCOUNTING'] = '1'
os.environ['AMD_NATIVE_FRAME_ACCOUNTING'] = '1'
os.environ['AMD_GPU_TIMESTAMP_PROFILE'] = '1'
os.environ['AMD_AMF_DIAG'] = '1'
os.environ['AMD_CHART_PATH'] = 'GPU_SPLIT'
os.environ['AMD_GAUGE_PATH'] = 'GPU'
os.environ['AMD_MAP_PATH'] = 'GPU'
os.environ['AMD_OVERLAY_PROFILE'] = '0'
{env_str}

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import ensure_records_list, extract_altitude_samples, extract_exposure_samples, extract_iso_samples, extract_speed_samples, extract_temperature_samples, extract_track_samples, interpolate_value, load_json_with_fallback, smooth_speed_samples
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

records = ensure_records_list(load_json_with_fallback(root / 'Video' / 'GX030120.json'))
tm = TelemetryDataManager(extract_speed_samples, extract_altitude_samples, extract_track_samples, extract_iso_samples, extract_exposure_samples, extract_temperature_samples, smooth_speed_samples, interpolate_value)
tm.load_gpmf_records(records)
tm.load_fit(root / 'Video' / 'Poranna_jazda_na_rowerze.fit')
tm.start_dt_utc = tm.speed_samples[0][0]

layout = json.load(open(root / 'def_layout.json', encoding='utf-8'))
speed = smooth_speed_samples(tm.speed_samples, 'moving_average', 5)
alt = smooth_speed_samples(tm.alt_samples, 'moving_average', 5)
track = tm.track_samples

out_mp4 = root / 'scratch' / f'{name}.mp4'
if out_mp4.exists():
    try: out_mp4.unlink()
    except: pass

res = stream_overlay_to_ffmpeg(
    ffmpeg_exe=r'C:\\tools\\ffmpeg.exe',
    input_files=[str(root / 'Video' / 'GX030120.MP4')],
    output_file=str(out_mp4),
    duration_s={frames} * (1001 / 30000),
    start_dt_utc=tm.start_dt_utc,
    tz_offset_hours=0.0,
    speed_samples=speed,
    track_samples=track,
    alt_samples=alt,
    field_samples={{'speed_samples': speed, 'track_samples': track, 'alt_samples': alt}},
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source('fit'),
    layout=layout,
    font_path='arial.ttf',
    encoder='amd_native',
)
print('Done', res)
"""
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-c", script], check=True)
    t1 = time.perf_counter()
    print(f"Finished {name} in {t1 - t0:.2f}s")


def analyze_pixel_parity_and_ranges():
    print(f"\n=======================================================")
    print(f"=== PIXEL PARITY & RANGE COMPARISON (5 TEST FRAMES) ===")
    print(f"=======================================================")
    
    test_frames = [30, 225, 450, 675, 899]
    
    # Check YUV files from oracle (1-pass) vs new VP limited (0-pass)
    # We dump them using separate naming or analyze the raw vs post norm
    for f in test_frames:
        p_raw = root / "scratch" / f"diag_vp_raw_frame_{f}.yuv"
        p_norm = root / "scratch" / f"diag_post_norm_frame_{f}.yuv"
        
        if not p_raw.exists():
            print(f"Frame {f}: diag files missing!")
            continue
        
        y_raw, u_raw, v_raw = read_nv12(str(p_raw))
        y_norm, u_norm, v_norm = read_nv12(str(p_norm))
        
        print(f"\n--- FRAME {f:3d} STATISTICAL PROFILE ---")
        print(f"  PLANE Y (VP Output):       min={np.min(y_raw):3d}, max={np.max(y_raw):3d}, mean={np.mean(y_raw):6.2f}, med={np.median(y_raw):3.0f}, p01={np.percentile(y_raw, 1):3.0f}, p99={np.percentile(y_raw, 99):3.0f}")
        print(f"  PLANE U (VP Output):       min={np.min(u_raw):3d}, max={np.max(u_raw):3d}, mean={np.mean(u_raw):6.2f}, med={np.median(u_raw):3.0f}")
        print(f"  PLANE V (VP Output):       min={np.min(v_raw):3d}, max={np.max(v_raw):3d}, mean={np.mean(v_raw):6.2f}, med={np.median(v_raw):3.0f}")

        # If we have oracle vs new VP comparison:
        # Let's check characteristic regions
        h, w = y_raw.shape
        regions = {
            "Dark Shadow": (int(h * 0.8), int(w * 0.2)),
            "Midtone Asphalt": (int(h * 0.7), int(w * 0.5)),
            "Bright Sky": (int(h * 0.1), int(w * 0.5)),
            "White Highlight": (int(h * 0.15), int(w * 0.8)),
            "Neutral Gray": (int(h * 0.5), int(w * 0.1)),
        }
        print("  Characteristic Regions (5x5 avg):")
        for r_name, (cy, cx) in regions.items():
            r_y = np.mean(y_raw[cy-2:cy+3, cx-2:cx+3])
            r_u = np.mean(u_raw[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
            r_v = np.mean(v_raw[cy//2-1:cy//2+2, cx//2-1:cx//2+2])
            print(f"    {r_name:16s}: Y={r_y:5.1f} | U={r_u:5.1f} | V={r_v:5.1f}")


if __name__ == "__main__":
    # 1. First, run test on 5 frames dump for Oracle (Legacy Full VP + 1 Normalize pass)
    run_single_process("etap8i_oracle_1pass", {
        "AMD_VP_COLORSPACE_MODE": "0",
        "AMD_NORMALIZE_PASSES": "1",
        "AMD_DUMP_RANGE_FRAMES": "30,225,450,675,899",
    }, 901)
    # Move oracle dump files to oracle names
    for f in [30, 225, 450, 675, 899]:
        p_raw = root / "scratch" / f"diag_vp_raw_frame_{f}.yuv"
        p_norm = root / "scratch" / f"diag_post_norm_frame_{f}.yuv"
        if p_norm.exists():
            p_norm.replace(root / "scratch" / f"oracle_1pass_frame_{f}.yuv")

    # 2. Run new VP Limited + 0 Normalize passes (Mode 1: Nominal Range 2->1)
    run_single_process("etap8i_new_vp_limited_run1", {
        "AMD_VP_COLORSPACE_MODE": "1",
        "AMD_NORMALIZE_PASSES": "0",
        "AMD_DUMP_RANGE_FRAMES": "30,225,450,675,899",
    }, 901)
    # Move new VP dump files
    for f in [30, 225, 450, 675, 899]:
        p_raw = root / "scratch" / f"diag_vp_raw_frame_{f}.yuv"
        if p_raw.exists():
            p_raw.replace(root / "scratch" / f"new_vp_limited_frame_{f}.yuv")

    # 3. Run 2 more benchmark runs for 3x900 stats with new production VP LIMITED
    run_single_process("etap8i_new_vp_limited_run2", {
        "AMD_VP_COLORSPACE_MODE": "1",
        "AMD_NORMALIZE_PASSES": "0",
        "AMD_DUMP_RANGE_FRAMES": "",
    }, 901)
    run_single_process("etap8i_new_vp_limited_run3", {
        "AMD_VP_COLORSPACE_MODE": "1",
        "AMD_NORMALIZE_PASSES": "0",
        "AMD_DUMP_RANGE_FRAMES": "",
    }, 901)
