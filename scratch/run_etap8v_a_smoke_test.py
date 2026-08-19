import os
import sys
import csv
import numpy as np
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.gui.layout_manager import normalize_layout
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

def run_smoke_test():
    print("=== ETAP 8V-A 300-FRAME GPU SMOKE TEST ===", flush=True)
    os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    os.environ["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
    os.environ["AMD_CPU_GPU_PIPELINE"] = "SYNC"
    os.environ["AMD_MAP_GPU_PATH"] = "DIRECT_AUTO"
    
    tm = TelemetryDataManager(
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
    records = ensure_records_list(load_json_with_fallback(v_1131.with_suffix(".json")))
    tm.load_gpmf_records(records)
    tm.load_fit(str(fit_1131))
    
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    
    # 1. DIRECT MAP ON (300 frames = 10.01 s)
    out_direct = root / "Raporty" / "etap8v_a_artifacts" / "smoke_direct_300f.mp4"
    if out_direct.exists(): out_direct.unlink()
    
    print("\n--- Running DIRECT MAP ON (300 frames) ---", flush=True)
    ok_direct = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_1131)],
        output_file=str(out_direct),
        duration_s=300 / 29.97,
        video_width=3840,
        video_height=2160,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2.0,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        font_path="assets/Roboto-Bold.ttf",
        layout=layout,
        field_samples=tm.fit_data or {},
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
    )
    
    # 2. MAP OFF (300 frames)
    layout_nomap = dict(layout)
    layout_nomap["track_map"] = dict(layout_nomap.get("track_map", {}))
    layout_nomap["track_map"]["enabled"] = False
    
    out_nomap = root / "Raporty" / "etap8v_a_artifacts" / "smoke_nomap_300f.mp4"
    if out_nomap.exists(): out_nomap.unlink()
    
    print("\n--- Running MAP OFF Control (300 frames) ---", flush=True)
    ok_nomap = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_1131)],
        output_file=str(out_nomap),
        duration_s=300 / 29.97,
        video_width=3840,
        video_height=2160,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2.0,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        font_path="assets/Roboto-Bold.ttf",
        layout=layout_nomap,
        field_samples=tm.fit_data or {},
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
    )
    
    print(f"\nExports finished: Direct={ok_direct}, NoMap={ok_nomap}", flush=True)
    
    # Analyze CSV Timelines
    csv_direct = out_direct.with_suffix(".mp4.gpu_timeline.csv")
    csv_nomap = out_nomap.with_suffix(".mp4.gpu_timeline.csv")
    
    print("\n=======================================================")
    print("=== GPU HARDWARE TIMESTAMP TIMELINE RECONCILIATION ===")
    print("=======================================================")
    
    def analyze_csv(p, label):
        if not p.exists():
            print(f"Missing {p}")
            return
        rows = []
        with open(p, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append({k: float(v) for k, v in r.items()})
        if not rows: return
        print(f"\n{label} ({len(rows)} frames):")
        for col in ['span_ms', 'vp_ms', 'charts_ms', 'gauge_ms', 'map_ms', 'hud_ms']:
            vals = [r[col] for r in rows]
            med = float(np.median(vals))
            p95 = float(np.percentile(vals, 95))
            print(f"  {col:10s}: Median = {med:6.3f} ms | P95 = {p95:6.3f} ms")

    analyze_csv(csv_direct, "DIRECT MAP ON")
    analyze_csv(csv_nomap, "MAP OFF CONTROL")
    print("=======================================================")

if __name__ == "__main__":
    run_smoke_test()
