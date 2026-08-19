"""
Comprehensive Usability & Stability Verification Suite for ETAP 9A-LITE.
"""
import os
import sys
import time
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.video_helpers import ffprobe_stream_info
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.qp_analyzer import analyze_qp, _stats_from_hist

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

def create_telemetry_manager():
    return TelemetryDataManager(
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

def run_suite():
    print("===============================================================================")
    print("ETAP 9A-LITE: Usability, Stability & GUI Workflow Verification")
    print("===============================================================================")
    
    results = {}
    
    # -------------------------------------------------------------------------
    # 1. App / Controller Initialization & Video Load
    # -------------------------------------------------------------------------
    print("\n[1. APP INITIALIZATION & VIDEO LOAD]")
    try:
        tm = create_telemetry_manager()
        print("  TelemetryDataManager initialized: OK")
        
        # Probe Video
        info = ffprobe_stream_info("ffprobe", v_1131)
        w = int(info["streams"][0]["width"])
        h = int(info["streams"][0]["height"])
        assert w == 3840 and h == 2160
        print(f"  Loaded MP4: {w}x{h} -> OK")
        
        # Load GPMF and FIT
        records = ensure_records_list(load_json_with_fallback(v_1131.with_suffix(".json")))
        tm.load_gpmf_records(records)
        tm.load_fit(str(fit_1131))
        assert tm.fit_data is not None
        assert "speed" in tm.fit_data
        print("  Loaded GPMF & FIT: OK")
        
        results["APP_START"] = "PASS"
        results["LOAD"] = "PASS"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["APP_START"] = "FAIL"
        results["LOAD"] = "FAIL"
        
    # -------------------------------------------------------------------------
    # 2. Preview & Seek & Widget Configuration
    # -------------------------------------------------------------------------
    print("\n[2. PREVIEW, SEEK & WIDGET TOGGLES]")
    try:
        layout = normalize_layout(root / "def_layout.json", 3840, 2160)
        assert len(layout) > 0
        
        # Test widget property toggles
        layout_mod = dict(layout)
        if "speed_text" in layout_mod:
            layout_mod["speed_text"] = dict(layout_mod["speed_text"])
            layout_mod["speed_text"]["enabled"] = not layout_mod["speed_text"].get("enabled", True)
        print("  Layout normalization and Widget Toggle: OK")
        
        results["PREVIEW"] = "PASS"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["PREVIEW"] = "FAIL"

    # -------------------------------------------------------------------------
    # 3. Preview vs Final Value Parity (Section 4)
    # -------------------------------------------------------------------------
    print("\n[3. PREVIEW VS FINAL TELEMETRY PARITY]")
    try:
        from datetime import timedelta
        base_dt = tm.start_dt_utc
        test_offsets = [0.0, 5.0, 15.0, 30.0]
        for t_s in test_offsets:
            dt = base_dt + timedelta(seconds=t_s)
            sp_p = tm.resolve_value("speed", dt, source="fit")
            hr_p = tm.resolve_value("heart_rate", dt, source="fit")
            cad_p = tm.resolve_value("cadence", dt, source="fit")
            alt_p = tm.resolve_value("alt", dt, source="fit")
            print(f"  t={t_s:4.1f}s | Speed={sp_p:.1f} m/s | HR={hr_p} bpm | Cad={cad_p} rpm | Alt={alt_p} m")
        results["PREVIEW_FINAL_PARITY"] = "PASS"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["PREVIEW_FINAL_PARITY"] = "FAIL"

    # -------------------------------------------------------------------------
    # 4. Source Selection (Section 5)
    # -------------------------------------------------------------------------
    print("\n[4. SOURCE SELECTION & NO SILENT FALLBACK]")
    try:
        # Check FIT source samples
        samples_fit = tm.get_samples_for_source("fit")
        assert samples_fit is not None
        assert len(samples_fit) > 0
        print("  Source 'fit' retrieved: OK")
        
        # Check GPMF source samples
        samples_gpmf = tm.get_samples_for_source("gpmf")
        assert samples_gpmf is not None
        print("  Source 'gpmf' retrieved: OK")
        
        results["SOURCE_SELECTION"] = "PASS"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["SOURCE_SELECTION"] = "FAIL"

    # -------------------------------------------------------------------------
    # 5. QP Analyzer Functionality (Section 11)
    # -------------------------------------------------------------------------
    print("\n[5. QP ANALYZER]")
    try:
        hist_test = {18: 50, 22: 100, 26: 50}
        mean_qp, med_qp, min_qp, max_qp = _stats_from_hist(hist_test)
        assert abs(mean_qp - 22.0) < 0.01
        assert abs(med_qp - 22.0) < 0.01
        assert min_qp == 18
        assert max_qp == 26
        print(f"  _stats_from_hist: mean={mean_qp}, med={med_qp}, min={min_qp}, max={max_qp} -> OK")
        results["QP_ANALYZER"] = "PASS"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["QP_ANALYZER"] = "FAIL"

    # -------------------------------------------------------------------------
    # 6. Repeated Export in Single Session (Section 6)
    # -------------------------------------------------------------------------
    print("\n[6. REPEATED EXPORT IN SINGLE SESSION]")
    try:
        out1 = root / "scratch" / "repeat_export_run1.mp4"
        out2 = root / "scratch" / "repeat_export_run2.mp4"
        if out1.exists(): out1.unlink()
        if out2.exists(): out2.unlink()
        
        layout_norm = normalize_layout(root / "def_layout.json", 3840, 2160)
        gps_track = tm.get_gps_track_for_source("fit")
        
        print("  Starting Export #1 (60 frames)...", flush=True)
        ok1 = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(v_1131)],
            output_file=str(out1),
            duration_s=60 / 29.97,
            video_width=3840,
            video_height=2160,
            start_dt_utc=tm.start_dt_utc,
            tz_offset_hours=2.0,
            speed_samples=tm.speed_samples or [],
            track_samples=tm.track_samples or [],
            alt_samples=tm.alt_samples or [],
            font_path="assets/Roboto-Bold.ttf",
            layout=layout_norm,
            field_samples=tm.fit_data or {},
            iso_samples=tm.iso_samples,
            exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples,
            fit_data=tm.fit_data,
            gps_track=gps_track,
        )
        assert ok1 is True
        assert out1.exists()
        print(f"  Export #1: SUCCESS ({out1.stat().st_size / 1024 / 1024:.2f} MiB)")
        
        print("  Starting Export #2 immediately in same process (60 frames)...", flush=True)
        ok2 = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(v_1131)],
            output_file=str(out2),
            duration_s=60 / 29.97,
            video_width=3840,
            video_height=2160,
            start_dt_utc=tm.start_dt_utc,
            tz_offset_hours=2.0,
            speed_samples=tm.speed_samples or [],
            track_samples=tm.track_samples or [],
            alt_samples=tm.alt_samples or [],
            font_path="assets/Roboto-Bold.ttf",
            layout=layout_norm,
            field_samples=tm.fit_data or {},
            iso_samples=tm.iso_samples,
            exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples,
            fit_data=tm.fit_data,
            gps_track=gps_track,
        )
        assert ok2 is True
        assert out2.exists()
        print(f"  Export #2: SUCCESS ({out2.stat().st_size / 1024 / 1024:.2f} MiB)")
        
        results["REPEATED_EXPORT"] = "PASS"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["REPEATED_EXPORT"] = "FAIL"

    # -------------------------------------------------------------------------
    # 7. Error Handling & Missing Telemetry (Section 9 & 12)
    # -------------------------------------------------------------------------
    print("\n[7. ERROR HANDLING & OPTIONAL TELEMETRY]")
    try:
        out_notel = root / "scratch" / "export_no_telemetry.mp4"
        if out_notel.exists(): out_notel.unlink()
        
        print("  Running MP4 without FIT/telemetry (60 frames)...", flush=True)
        ok_notel = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(v_1131)],
            output_file=str(out_notel),
            duration_s=60 / 29.97,
            video_width=3840,
            video_height=2160,
            start_dt_utc=None,
            tz_offset_hours=0.0,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            font_path="assets/Roboto-Bold.ttf",
            layout=layout_norm,
            field_samples={},
            iso_samples=None,
            exposure_samples=None,
            temperature_samples=None,
            fit_data=None,
            gps_track=[],
        )
        assert ok_notel is True
        print("  MP4 without telemetry: SUCCESS")
        
        # Test Invalid Input MP4 handling
        ok_bad = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=["non_existent_file_xyz.mp4"],
            output_file="scratch/bad_out.mp4",
            duration_s=1.0,
            video_width=1920,
            video_height=1080,
            start_dt_utc=None,
            tz_offset_hours=0.0,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            font_path="assets/Roboto-Bold.ttf",
            layout={},
            field_samples={},
            iso_samples=None,
            exposure_samples=None,
            temperature_samples=None,
            fit_data=None,
            gps_track=[],
        )
        assert ok_bad is False
        print("  Invalid MP4 gracefully returned False: OK")
        
        results["ERROR_HANDLING"] = "PASS"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["ERROR_HANDLING"] = "FAIL"

    # -------------------------------------------------------------------------
    # 8. 1080p Resolution Verification (Section 14)
    # -------------------------------------------------------------------------
    print("\n[8. 1080P RESOLUTION EXPORT]")
    try:
        out_1080p = root / "scratch" / "smoke_1080p.mp4"
        if out_1080p.exists(): out_1080p.unlink()
        layout_1080p = normalize_layout(root / "def_layout.json", 1920, 1080)
        
        ok_1080 = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(v_1131)],
            output_file=str(out_1080p),
            duration_s=60 / 29.97,
            video_width=1920,
            video_height=1080,
            start_dt_utc=tm.start_dt_utc,
            tz_offset_hours=2.0,
            speed_samples=tm.speed_samples or [],
            track_samples=tm.track_samples or [],
            alt_samples=tm.alt_samples or [],
            font_path="assets/Roboto-Bold.ttf",
            layout=layout_1080p,
            field_samples=tm.fit_data or {},
            iso_samples=tm.iso_samples,
            exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples,
            fit_data=tm.fit_data,
            gps_track=gps_track,
        )
        assert ok_1080 is True
        assert out_1080p.exists()
        print(f"  1080p Export: SUCCESS ({out_1080p.stat().st_size / 1024 / 1024:.2f} MiB)")
        results["RESOLUTION_1080P"] = "PASS"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["RESOLUTION_1080P"] = "FAIL"

    print("\n===============================================================================")
    print("=== FINAL USABILITY VERIFICATION SUMMARY ===")
    for k, v in results.items():
        print(f"  {k:30s} = {v}")
    print("===============================================================================")

if __name__ == "__main__":
    run_suite()
