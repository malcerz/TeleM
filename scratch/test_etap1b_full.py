"""Comprehensive ETAP 1B Test, Validation, Parity & Performance Suite."""
import os
import sys
import json
import time
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

VIDEO = root / "Video" / "GX010115.MP4"
META = root / "Video" / "GX010115.json"
FIT = root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = root / "presets" / "cycling_dashboard_v10.json"
OUT_DIR = root / "scratch" / "etap1b_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_data():
    with open(LAYOUT_PATH, "r", encoding="utf-8") as f:
        layout = json.load(f)
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
        get_rotation_meta_fn=get_rotation_from_metadata,
        get_container_rotation_fn=get_container_rotation,
        find_meta_json_fn=find_metadata_json,
        find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
        load_telemetry_fn=lambda *a: None,
        ensure_records_fn=ensure_records_list,
        load_json_fallback_fn=load_json_with_fallback,
        write_records_fn=lambda p, r: None,
        extract_samples_exiftool_fn=lambda f: [],
        extract_altitude_exiftool_fn=lambda f: [],
        extract_gps_track_fn=extract_gps_track,
        find_gps_anchor_fn=lambda r: None,
        smooth_values_fn=smooth_speed_values,
        extract_accelerometer_fn=extract_accelerometer_samples,
        extract_gyroscope_fn=extract_gyroscope_samples,
    )
    with open(META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    records = ensure_records_list(meta)
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    return layout, telemetry

def extract_frames_from_video(mp4_path, out_prefix, frame_indices=[5, 15, 25, 45, 65]):
    out_paths = {}
    for idx in frame_indices:
        out_png = OUT_DIR / f"{out_prefix}_f{idx:03d}.png"
        cmd = [
            "ffmpeg", "-y", "-i", str(mp4_path),
            "-vf", f"select=eq(n\\,{idx})", "-vframes", "1", str(out_png)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        out_paths[idx] = out_png
    return out_paths

def render_pass(layout, telemetry, out_mp4, duration_s, after_map_gpu=False, width=1920, height=1080):
    if out_mp4.exists():
        out_mp4.unlink()
    
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1" if after_map_gpu else "0"
    os.environ["AMD_AFTER_MAP_CHART_CAPTURE_DIAG"] = "1"
    
    t0 = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=duration_s,
        video_width=width,
        video_height=height,
        start_dt_utc=telemetry.start_dt_utc,
        tz_offset_hours=2.0,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        font_path="",
        layout=layout,
        field_samples=telemetry.fit_data,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        target_fps=59.94005994,
        video_bitrate="12M" if width == 1920 else "40M",
        quality="speed",
    )
    t1 = time.perf_counter()
    assert ok, f"Export failed for {out_mp4}"
    return t1 - t0

def compare_images(img1_path, img2_path, diff_out_path=None, roi=None):
    im1 = np.array(Image.open(img1_path).convert("RGB"), dtype=np.float32)
    im2 = np.array(Image.open(img2_path).convert("RGB"), dtype=np.float32)
    
    if roi is not None:
        rx, ry, rw, rh = roi
        im1 = im1[ry:ry+rh, rx:rx+rw]
        im2 = im2[ry:ry+rh, rx:rx+rw]
        
    diff = np.abs(im1 - im2)
    max_diff = float(np.max(diff))
    mean_diff = float(np.mean(diff))
    mse = float(np.mean((im1 - im2) ** 2))
    psnr = 100.0 if mse == 0 else float(20 * np.log10(255.0 / np.sqrt(mse)))
    
    if diff_out_path is not None:
        diff_img = np.clip(diff * 5.0, 0, 255).astype(np.uint8)  # 5x amplified diff
        Image.fromarray(diff_img).save(diff_out_path)
        
    return {
        "max_delta": max_diff,
        "mean_delta": mean_diff,
        "mse": mse,
        "psnr": psnr,
    }

def main():
    print("=" * 80)
    print("ETAP 1B: NATIVE AFTER-MAP GPU_SPLIT CHARTS TEST SUITE")
    print("=" * 80)
    
    layout, telemetry = load_data()
    
    # ── 1. Render 75 frames Baseline (AMD_AFTER_MAP_CHART_GPU=0) ──
    baseline_mp4 = OUT_DIR / "baseline_75f.mp4"
    print("\n[1/5] Rendering 75 frames Baseline (AMD_AFTER_MAP_CHART_GPU=0)...")
    dur_base = render_pass(layout, telemetry, baseline_mp4, duration_s=1.26, after_map_gpu=False)
    fps_base = 75 / dur_base
    print(f"      -> Baseline: {dur_base:.2f}s ({fps_base:.1f} FPS)")
    
    # ── 2. Render 75 frames Native AFTER-MAP GPU (AMD_AFTER_MAP_CHART_GPU=1) ──
    gpu_mp4 = OUT_DIR / "gpu_after_map_75f.mp4"
    print("\n[2/5] Rendering 75 frames Native AFTER-MAP GPU (AMD_AFTER_MAP_CHART_GPU=1)...")
    dur_gpu = render_pass(layout, telemetry, gpu_mp4, duration_s=1.26, after_map_gpu=True)
    fps_gpu = 75 / dur_gpu
    print(f"      -> GPU AFTER-MAP: {dur_gpu:.2f}s ({fps_gpu:.1f} FPS)")
    
    # ── 3. Extract Frames for Parity & Z-Order Comparison ──
    frames = [5, 15, 25, 45, 65]
    print(f"\n[3/5] Extracting frames {frames} using exact select filter...")
    base_frames = extract_frames_from_video(baseline_mp4, "base", frames)
    gpu_frames = extract_frames_from_video(gpu_mp4, "gpu", frames)
    
    print("\n[4/5] Computing Pixel Parity & Overlap Metrics...")
    results = {}
    
    # Check whole canvas & ROIs
    hr_roi = (870, 770, 526, 233)
    cadence_roi = (198, 770, 526, 233)
    intersection_roi = (870, 770, 369, 66)
    
    print("-" * 80)
    print(f"{'Frame':<8}{'Region':<20}{'Max Delta':<12}{'Mean Delta':<12}{'PSNR (dB)':<12}{'Status':<10}")
    print("-" * 80)
    
    for idx in frames:
        b_png = base_frames[idx]
        g_png = gpu_frames[idx]
        
        # Whole frame
        diff_png = OUT_DIR / f"diff_full_f{idx:03d}.png"
        metrics_full = compare_images(b_png, g_png, diff_png)
        status_full = "PASS" if metrics_full["mean_delta"] <= 2.0 and metrics_full["psnr"] >= 35.0 else "WARN"
        print(f"f{idx:<7}{'Full Frame':<20}{metrics_full['max_delta']:<12.1f}{metrics_full['mean_delta']:<12.3f}{metrics_full['psnr']:<12.2f}{status_full:<10}")
        
        # HR ROI
        metrics_hr = compare_images(b_png, g_png, roi=hr_roi)
        print(f"f{idx:<7}{'HR Chart ROI':<20}{metrics_hr['max_delta']:<12.1f}{metrics_hr['mean_delta']:<12.3f}{metrics_hr['psnr']:<12.2f}{'PASS' if metrics_hr['psnr'] >= 30.0 else 'WARN':<10}")
        
        # Cadence ROI
        metrics_cad = compare_images(b_png, g_png, roi=cadence_roi)
        print(f"f{idx:<7}{'Cadence ROI':<20}{metrics_cad['max_delta']:<12.1f}{metrics_cad['mean_delta']:<12.3f}{metrics_cad['psnr']:<12.2f}{'PASS' if metrics_cad['psnr'] >= 30.0 else 'WARN':<10}")
        
        # Overlap Intersection ROI
        metrics_inter = compare_images(b_png, g_png, roi=intersection_roi)
        print(f"f{idx:<7}{'Dist/HR Overlap':<20}{metrics_inter['max_delta']:<12.1f}{metrics_inter['mean_delta']:<12.3f}{metrics_inter['psnr']:<12.2f}{'PASS' if metrics_inter['psnr'] >= 30.0 else 'WARN':<10}")
        print("-" * 80)
        
        results[idx] = {
            "full": metrics_full,
            "hr": metrics_hr,
            "cadence": metrics_cad,
            "intersection": metrics_inter,
        }

    with open(OUT_DIR / "parity_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print("\n[5/5] Performance Benchmark: 300 Frames at 1080p and 4K...")
    # 1080p benchmark
    bench_1080_base_mp4 = OUT_DIR / "bench_1080_base.mp4"
    bench_1080_gpu_mp4 = OUT_DIR / "bench_1080_gpu.mp4"
    
    print("      -> Running 1080p Baseline (300 frames)...")
    t_1080_base = render_pass(layout, telemetry, bench_1080_base_mp4, duration_s=5.01, after_map_gpu=False, width=1920, height=1080)
    fps_1080_base = 300 / t_1080_base
    
    print("      -> Running 1080p GPU AFTER-MAP (300 frames)...")
    t_1080_gpu = render_pass(layout, telemetry, bench_1080_gpu_mp4, duration_s=5.01, after_map_gpu=True, width=1920, height=1080)
    fps_1080_gpu = 300 / t_1080_gpu
    
    # 4K benchmark
    bench_4k_base_mp4 = OUT_DIR / "bench_4k_base.mp4"
    bench_4k_gpu_mp4 = OUT_DIR / "bench_4k_gpu.mp4"
    
    print("      -> Running 4K Baseline (300 frames)...")
    t_4k_base = render_pass(layout, telemetry, bench_4k_base_mp4, duration_s=5.01, after_map_gpu=False, width=3840, height=2160)
    fps_4k_base = 300 / t_4k_base
    
    print("      -> Running 4K GPU AFTER-MAP (300 frames)...")
    t_4k_gpu = render_pass(layout, telemetry, bench_4k_gpu_mp4, duration_s=5.01, after_map_gpu=True, width=3840, height=2160)
    fps_4k_gpu = 300 / t_4k_gpu
    
    print("\n" + "=" * 80)
    print("FINAL ETAP 1B PERFORMANCE SUMMARY (300 Frames)")
    print("=" * 80)
    print(f"1080p Baseline (CPU_REFERENCE):    {t_1080_base:.2f} s | {fps_1080_base:.2f} FPS")
    print(f"1080p Native GPU AFTER-MAP:       {t_1080_gpu:.2f} s | {fps_1080_gpu:.2f} FPS (Delta: {fps_1080_gpu - fps_1080_base:+.2f} FPS)")
    print(f"4K    Baseline (CPU_REFERENCE):    {t_4k_base:.2f} s | {fps_4k_base:.2f} FPS")
    print(f"4K    Native GPU AFTER-MAP:       {t_4k_gpu:.2f} s | {fps_4k_gpu:.2f} FPS (Delta: {fps_4k_gpu - fps_4k_base:+.2f} FPS)")
    print("=" * 80)

    bench_summary = {
        "1080p_baseline_sec": t_1080_base,
        "1080p_baseline_fps": fps_1080_base,
        "1080p_gpu_sec": t_1080_gpu,
        "1080p_gpu_fps": fps_1080_gpu,
        "4k_baseline_sec": t_4k_base,
        "4k_baseline_fps": fps_4k_base,
        "4k_gpu_sec": t_4k_gpu,
        "4k_gpu_fps": fps_4k_gpu,
    }
    with open(OUT_DIR / "benchmark_summary.json", "w", encoding="utf-8") as f:
        json.dump(bench_summary, f, indent=2)

if __name__ == "__main__":
    main()
