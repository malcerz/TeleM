"""ETAP 8K: Comprehensive Production Validation and Benchmarking Script."""
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


def run_full_suite():
    # Only run full 180s since prod_dump, prod_run1, prod_run2, prod_run3 are already finished!
    run_single_process("etap8k_prod_full180s", {}, 5395)


if __name__ == "__main__":
    run_full_suite()
