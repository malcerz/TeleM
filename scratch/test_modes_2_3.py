"""Test Mode 2 and Mode 3 for VideoProcessorSetStreamColorSpace1."""
import os, sys, json, subprocess
from pathlib import Path

root = Path("c:/_DEV/TeleM")

def test_mode(mode_num):
    print(f"\n=======================================================")
    print(f"=== TESTING AMD_VP_COLORSPACE_MODE = {mode_num} ===")
    print(f"=======================================================")
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
os.environ['AMD_VP_COLORSPACE_MODE'] = '{mode_num}'
os.environ['AMD_NORMALIZE_PASSES'] = '0'
os.environ['AMD_DUMP_RANGE_FRAMES'] = '30'

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

out_mp4 = root / 'scratch' / f'test_mode_{mode_num}.mp4'
if out_mp4.exists():
    try: out_mp4.unlink()
    except: pass

res = stream_overlay_to_ffmpeg(
    ffmpeg_exe=r'C:\\tools\\ffmpeg.exe',
    input_files=[str(root / 'Video' / 'GX030120.MP4')],
    output_file=str(out_mp4),
    duration_s=35 * (1001 / 30000),
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
    subprocess.run([sys.executable, "-c", script], check=True)

if __name__ == "__main__":
    test_mode(2)
    test_mode(3)
