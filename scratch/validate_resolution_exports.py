"""Validate 4K, 1080p, and 720p exports in real AMD Native D3D11 runtime."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.video_helpers import ffprobe_stream_info, parse_fps

def run_validation():
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    json_path = root / "Video" / "GX030120.json"
    mp4_in = root / "Video" / "GX030120.MP4"
    records = ensure_records_list(load_json_with_fallback(json_path))
    tm = TelemetryDataManager(
        extract_speed_samples, extract_altitude_samples, extract_track_samples,
        extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
        smooth_speed_samples, interpolate_value
    )
    tm.load_gpmf_records(records)
    tm.load_fit(fit_path)
    tm.start_dt_utc = tm.speed_samples[0][0]

    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    
    speed = smooth_speed_samples(extract_speed_samples(records), "moving_average", 5)
    track = extract_track_samples(records)
    alt = smooth_speed_samples(extract_altitude_samples(records), "moving_average", 5)
    
    field_samples = {
        "speed_samples": speed,
        "track_samples": track,
        "alt_samples": alt,
        "accel_x_samples": tm.accel_x_samples,
        "accel_y_samples": tm.accel_y_samples,
        "accel_z_samples": tm.accel_z_samples,
        "accel_magnitude_samples": tm.accel_magnitude_samples,
        "gyro_x_samples": tm.gyro_x_samples,
        "gyro_y_samples": tm.gyro_y_samples,
        "gyro_z_samples": tm.gyro_z_samples,
        "gyro_magnitude_samples": tm.gyro_magnitude_samples,
    }
    
    gps_track = tm.get_gps_track_for_source("fit")
    ffmpeg_exe = r"C:\tools\ffmpeg.exe"
    ffprobe_exe = r"C:\tools\ffprobe.exe"
    
    out_dir = root / "scratch" / "validation_exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    test_configs = [
        ("4k", "4k", 3840, 2160),
        ("1080p", "1080p", 1920, 1080),
        ("720p", "720p", 1280, 720),
    ]
    
    results = {}
    
    for label, res_name, exp_w, exp_h in test_configs:
        out_mp4 = out_dir / f"export_{label}.mp4"
        print(f"\n=======================================================")
        print(f"RUNNING VALIDATION EXPORT: {label} ({res_name}) -> target {exp_w}x{exp_h}")
        print(f"=======================================================")
        
        # 60 frames @ 29.97 fps = ~2.002s
        duration_s = 60.0 * (1001.0 / 30000.0)
        
        t0 = time.perf_counter()
        stream_overlay_to_ffmpeg(
            ffmpeg_exe=ffmpeg_exe,
            input_files=[str(mp4_in)],
            output_file=str(out_mp4),
            duration_s=duration_s,
            start_dt_utc=tm.start_dt_utc,
            tz_offset_hours=2,
            speed_samples=speed,
            track_samples=track,
            alt_samples=alt,
            font_path="C:/_DEV/TeleM/resources/fonts/Roboto-Bold.ttf",
            layout=layout,
            field_samples=field_samples,
            target_fps=29.97,
            update_rate_step=1,
            max_distance_m=track[-1][1] if track else 0,
            workers=4,
            iso_samples=tm.iso_samples,
            exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples,
            fit_data=tm.fit_data,
            gps_track=gps_track,
            encoder="amd",
            gpu=0,
            resolution_name=res_name,
            video_bitrate="40M",
            rotation_degrees=0,
            container_rotation=0,
            overlay_w=exp_w,
            overlay_h=exp_h,
            render_w=exp_w,
            render_h=exp_h,
        )
        elapsed = time.perf_counter() - t0
        print(f"Export {label} finished in {elapsed:.2f}s")
        
        # Probe resulting MP4
        info = ffprobe_stream_info(ffprobe_exe, out_mp4)
        streams = info.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
        
        act_w = int(v_stream.get("width", 0))
        act_h = int(v_stream.get("height", 0))
        fps_act = parse_fps(v_stream.get("r_frame_rate", "0/0"))
        has_audio = bool(a_stream)
        
        print(f"PROBE RESULT for {label}:")
        print(f"  Width: {act_w} (expected {exp_w}) -> {'PASS' if act_w == exp_w else 'FAIL'}")
        print(f"  Height: {act_h} (expected {exp_h}) -> {'PASS' if act_h == exp_h else 'FAIL'}")
        print(f"  FPS: {fps_act:.2f}")
        print(f"  Audio stream present: {has_audio} ({a_stream.get('codec_name', 'none')})")
        
        # Extract frame 30 to check map & HUD
        frame_png = out_dir / f"frame_30_{label}.png"
        pts_s = 30.0 * (1001.0 / 30000.0)
        subprocess.run([
            ffmpeg_exe, "-y", "-ss", f"{pts_s:.3f}", "-i", str(out_mp4),
            "-vframes", "1", "-q:v", "2", str(frame_png)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if frame_png.exists():
            f_img = Image.open(frame_png)
            print(f"  Extracted frame 30 image size: {f_img.size}")
            # Map bbox for this resolution
            from src.indicators.helpers import s
            map_w = s(layout["indicators"]["track_map"].get("size", 0.1), exp_w)
            rx = s(layout["indicators"]["track_map"]["x"], exp_w)
            ry = s(layout["indicators"]["track_map"]["y"], exp_h)
            dst_bbox = (int(rx - map_w // 2), int(ry - map_w // 2), int(map_w), int(map_w))
            
            map_crop = f_img.crop((dst_bbox[0], dst_bbox[1], dst_bbox[0] + dst_bbox[2], dst_bbox[1] + dst_bbox[3]))
            map_crop_png = out_dir / f"map_crop_30_{label}.png"
            map_crop.save(map_crop_png)
            
            arr = np.array(map_crop)
            print(f"  Map crop {label}: size={map_crop.size}, min={arr.min()}, max={arr.max()}, mean={arr.mean():.2f}")
            
        results[label] = {
            "expected": (exp_w, exp_h),
            "actual": (act_w, act_h),
            "pass": (act_w == exp_w and act_h == exp_h),
            "audio": has_audio,
        }
        
    print("\n=======================================================")
    print("FINAL SUMMARY:")
    for k, v in results.items():
        print(f"  {k:8s}: Expected {v['expected']}, Actual {v['actual']} -> {'PASS' if v['pass'] else 'FAIL'}, Audio: {v['audio']}")

if __name__ == "__main__":
    run_validation()
