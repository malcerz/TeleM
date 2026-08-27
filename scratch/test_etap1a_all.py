"""Comprehensive test suite for AMD ETAP 1A.

Tests:
  TEST A — Existing GPU_SPLIT (HR + Cadence without map)
  TEST B — BEFORE-MAP (HR, Cadence, track_map)
  TEST C — AFTER-MAP (track_map, HR, Cadence) with AMD_AFTER_MAP_CHART_CAPTURE_DIAG=1
  TEST D — Full preset v10 with AMD_AFTER_MAP_CHART_CAPTURE_DIAG=1
  PIXEL PARITY — Full preset v10 (flag OFF) vs pre-edit baseline
"""

import copy
import json
import os
import subprocess
import sys
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
OUT_DIR = root / "scratch" / "etap1a_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PARITY_DIR = root / "scratch" / "parity_test"

HR = "fit_heart_rate_text"
CAD = "fit_cadence_text"
MAP = "track_map"

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

def layout_from_keys(base: dict, ordered_keys: list[str]) -> dict:
    out = copy.deepcopy(base)
    inds = {}
    for key in ordered_keys:
        if key in base.get("indicators", {}):
            inds[key] = copy.deepcopy(base["indicators"][key])
            inds[key]["enabled"] = True
    out["indicators"] = inds
    out["custom_texts"] = []
    return out

def run_export(name: str, layout: dict, telemetry, env_overrides: dict = None, duration_s: float = 0.5):
    env = {
        "AMD_TELEMETRY_MODE": "PRECOMPUTED",
        "AMD_NATIVE_HUD_MODE": "GPU_HUD",
        "AMD_NATIVE_DECODE_MODE": "GPU_HUD_D3D11VA",
        "AMD_MAP_PATH": "GPU",
        "AMD_CHART_PATH": "GPU_SPLIT",
        "AMD_GAUGE_PATH": "GPU",
        "AMD_ABOVE_DIRTY_MODE": "EXACT",
        "AMD_NATIVE_PROFILING": "1",
    }
    if env_overrides:
        env.update(env_overrides)
    
    old_env = {}
    for k, v in env.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = str(v)
        
    out_mp4 = OUT_DIR / f"{name}.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
    prof_path = Path(str(out_mp4) + ".amd_profile.json")
    if prof_path.exists():
        prof_path.unlink()
        
    try:
        ok = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(VIDEO)],
            output_file=str(out_mp4),
            duration_s=duration_s,
            video_width=1920,
            video_height=1080,
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
            target_fps=60.0,
        )
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
                
    profile = {}
    if prof_path.exists():
        with open(prof_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
            
    return ok, out_mp4, profile

def test_a(layout, telemetry):
    print("\n" + "=" * 60)
    print("TEST A: Existing GPU_SPLIT (HR + Cadence without map)")
    print("=" * 60)
    lay = layout_from_keys(layout, [HR, CAD])
    ok, mp4, prof = run_export("test_a_hrcad_nomap", lay, telemetry)
    
    etap5k = prof.get("etap5k", {})
    etap1a = prof.get("etap1a", {})
    active_charts = prof.get("etap5j", {}).get("active_gpu_charts", [])
    static_uploads = etap5k.get("static_uploads", 0)
    dynamic_uploads = etap5k.get("dynamic_uploads", 0)
    
    print(f"  OK: {ok}")
    print(f"  active_gpu_charts: {active_charts}")
    print(f"  static_uploads: {static_uploads}")
    print(f"  dynamic_uploads: {dynamic_uploads}")
    print(f"  before_map_chart_keys: {etap1a.get('before_map_chart_keys')}")
    print(f"  after_map_chart_keys: {etap1a.get('after_map_chart_keys')}")
    
    passed = (
        ok
        and len(active_charts) == 2
        and static_uploads >= 2
        and dynamic_uploads > 0
        and etap1a.get("before_map_chart_keys") == sorted([CAD, HR])
        and etap1a.get("after_map_chart_keys") == []
    )
    print(f"  TEST A Result: {'PASS' if passed else 'FAIL'}")
    return passed, prof

def test_b(layout, telemetry):
    print("\n" + "=" * 60)
    print("TEST B: BEFORE-MAP (HR, Cadence, track_map)")
    print("=" * 60)
    lay = layout_from_keys(layout, [HR, CAD, MAP])
    ok, mp4, prof = run_export("test_b_before_map", lay, telemetry)
    
    etap5k = prof.get("etap5k", {})
    etap1a = prof.get("etap1a", {})
    active_charts = prof.get("etap5j", {}).get("active_gpu_charts", [])
    static_uploads = etap5k.get("static_uploads", 0)
    dynamic_uploads = etap5k.get("dynamic_uploads", 0)
    
    print(f"  OK: {ok}")
    print(f"  active_gpu_charts: {active_charts}")
    print(f"  static_uploads: {static_uploads}")
    print(f"  dynamic_uploads: {dynamic_uploads}")
    print(f"  before_map_chart_keys: {etap1a.get('before_map_chart_keys')}")
    print(f"  after_map_chart_keys: {etap1a.get('after_map_chart_keys')}")
    print(f"  gpu_chart_keys_before_map: {etap1a.get('gpu_chart_keys_before_map')}")
    
    passed = (
        ok
        and len(active_charts) == 2
        and static_uploads >= 2
        and dynamic_uploads > 0
        and etap1a.get("before_map_chart_keys") == sorted([CAD, HR])
        and etap1a.get("after_map_chart_keys") == []
        and etap1a.get("gpu_chart_keys_before_map") == sorted([CAD, HR])
    )
    print(f"  TEST B Result: {'PASS' if passed else 'FAIL'}")
    return passed, prof

def test_c(layout, telemetry):
    print("\n" + "=" * 60)
    print("TEST C: AFTER-MAP (track_map, HR, Cadence) with AMD_AFTER_MAP_CHART_CAPTURE_DIAG=1")
    print("=" * 60)
    lay = layout_from_keys(layout, [MAP, HR, CAD])
    ok, mp4, prof = run_export(
        "test_c_after_map", lay, telemetry,
        env_overrides={"AMD_AFTER_MAP_CHART_CAPTURE_DIAG": "1"}
    )
    
    etap5k = prof.get("etap5k", {})
    etap1a = prof.get("etap1a", {})
    active_charts = prof.get("etap5j", {}).get("active_gpu_charts", [])
    static_uploads = etap5k.get("static_uploads", 0)
    dynamic_uploads = etap5k.get("dynamic_uploads", 0)
    after_captures = etap1a.get("after_map_captures_performed", 0)
    native_blend = etap1a.get("native_after_map_blend_active", True)
    
    print(f"  OK: {ok}")
    print(f"  active_gpu_charts (before-map): {active_charts}")
    print(f"  before_map_chart_keys: {etap1a.get('before_map_chart_keys')}")
    print(f"  after_map_chart_keys: {etap1a.get('after_map_chart_keys')}")
    print(f"  gpu_chart_keys_after_map: {etap1a.get('gpu_chart_keys_after_map')}")
    print(f"  after_map_captures_performed: {after_captures}")
    print(f"  native_after_map_blend_active: {native_blend}")
    
    passed = (
        ok
        and active_charts == [] # No charts blended before map!
        and etap1a.get("before_map_chart_keys") == []
        and etap1a.get("after_map_chart_keys") == sorted([CAD, HR])
        and after_captures > 0 # Diagnostic capture succeeded!
        and native_blend is False # No native blend!
    )
    print(f"  TEST C Result: {'PASS' if passed else 'FAIL'}")
    return passed, prof

def test_d(layout, telemetry):
    print("\n" + "=" * 60)
    print("TEST D: Full Preset v10 with AMD_AFTER_MAP_CHART_CAPTURE_DIAG=1")
    print("=" * 60)
    ok, mp4, prof = run_export(
        "test_d_full_v10", layout, telemetry,
        env_overrides={"AMD_AFTER_MAP_CHART_CAPTURE_DIAG": "1"}
    )
    
    etap1a = prof.get("etap1a", {})
    active_charts = prof.get("etap5j", {}).get("active_gpu_charts", [])
    after_captures = etap1a.get("after_map_captures_performed", 0)
    native_blend = etap1a.get("native_after_map_blend_active", True)
    
    print(f"  OK: {ok}")
    print(f"  active_gpu_charts (before-map): {active_charts}")
    print(f"  before_map_chart_keys: {etap1a.get('before_map_chart_keys')}")
    print(f"  after_map_chart_keys: {etap1a.get('after_map_chart_keys')}")
    print(f"  after_map_captures_performed: {after_captures}")
    print(f"  native_after_map_blend_active: {native_blend}")
    
    passed = (
        ok
        and active_charts == []
        and etap1a.get("before_map_chart_keys") == []
        and etap1a.get("after_map_chart_keys") == sorted([CAD, HR])
        and after_captures > 0
        and native_blend is False
    )
    print(f"  TEST D Result: {'PASS' if passed else 'FAIL'}")
    return passed, prof

def test_pixel_parity(layout, telemetry):
    print("\n" + "=" * 60)
    print("PIXEL PARITY TEST: Full Preset v10 (Flag OFF) vs Pre-edit Baseline")
    print("=" * 60)
    ok, mp4, prof = run_export(
        "parity_after", layout, telemetry,
        env_overrides={"AMD_AFTER_MAP_CHART_CAPTURE_DIAG": "0"}
    )
    
    frame_indices = [5, 15, 25]
    all_match = True
    for idx in frame_indices:
        before_png = PARITY_DIR / f"before_f{idx:03d}.png"
        after_png = OUT_DIR / f"after_f{idx:03d}.png"
        
        pts_time = idx / 60.0
        cmd = [
            "ffmpeg", "-y", "-ss", f"{pts_time:.4f}", "-i", str(mp4),
            "-frames:v", "1", str(after_png)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        if not before_png.exists():
            print(f"  Frame {idx}: Baseline {before_png} not found!")
            all_match = False
            continue
            
        img_b = np.array(Image.open(before_png).convert("RGB"))
        img_a = np.array(Image.open(after_png).convert("RGB"))
        
        diff = np.abs(img_a.astype(int) - img_b.astype(int))
        max_diff = int(np.max(diff))
        mae = float(np.mean(diff))
        
        match = (max_diff == 0)
        print(f"  Frame {idx:03d}: max_diff={max_diff}, mae={mae:.4f} -> {'EXACT MATCH' if match else 'MISMATCH'}")
        if not match:
            all_match = False
            
    print(f"  PIXEL PARITY Result: {'PASS' if all_match else 'FAIL'}")
    return all_match

def main():
    print("============================================================")
    print("TeleM AMD ETAP 1A — Verification Test Suite")
    print("============================================================")
    
    layout, telemetry = load_data()
    
    results = {}
    results["test_a"], _ = test_a(layout, telemetry)
    results["test_b"], _ = test_b(layout, telemetry)
    results["test_c"], _ = test_c(layout, telemetry)
    results["test_d"], _ = test_d(layout, telemetry)
    results["pixel_parity"] = test_pixel_parity(layout, telemetry)
    
    print("\n" + "=" * 60)
    print("SUMMARY OF ALL TESTS")
    print("=" * 60)
    for k, v in results.items():
        print(f"  {k:<20}: {'PASS' if v else 'FAIL'}")
        
    all_pass = all(results.values())
    print(f"\nOVERALL ETAP 1A STATUS: {'ALL PASS' if all_pass else 'FAILURES DETECTED'}")
    return all_pass

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
