"""ETAP 10U: AMD ABOVE upload-buffer A/B — COPY vs DIRECT.

Run:  python scratch/benchmark_etap10u_ab.py <COPY|DIRECT> <suffix> [--verify]
Writes: scratch/etap10u_<suffix>.mp4 + .amd_profile.json
This is a temporary harness; removed at the end of ETAP 10U.
"""

import ctypes
import json
import os
import sys
import subprocess
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, load_json_with_fallback,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "Video" / "GX010115.MP4"
JSON = ROOT / "Video" / "GX010115.json"
FIT = ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT = ROOT / "presets" / "cycling_dashboard_v10.json"
FFMPEG = "ffmpeg"


def build_telemetry():
    with open(LAYOUT, "r", encoding="utf-8") as f:
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
    with open(JSON, "r", encoding="utf-8") as f:
        meta = json.load(f)
    records = ensure_records_list(meta)
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    return telemetry, layout


def run_export(mode: str, suffix: str, verify: bool = False):
    import src.ffmpeg.amd_native_exporter as exporter

    if verify and mode == "DIRECT":
        real = exporter._above_region_pointer
        state = {"frames_checked": 0, "frames": 0, "errors": []}

        def verifying(r_bytes, m):
            if m == "DIRECT" and state["frames"] < 12:
                ptr = real(r_bytes, m)
                read = ctypes.string_at(ptr, len(r_bytes))
                if read != r_bytes:
                    state["errors"].append(
                        f"frame region mismatch: len={len(r_bytes)}")
                state["frames_checked"] += 1
                return ptr
            return real(r_bytes, m)

        exporter._above_region_pointer = verifying

    telemetry, layout = build_telemetry()
    out_mp4 = ROOT / "scratch" / f"etap10u_{suffix}.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
    os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    os.environ["AMD_NATIVE_DECODE_MODE"] = "GPU_HUD_D3D11VA"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_CHART_PATH"] = "CPU_REFERENCE"
    os.environ["AMD_GAUGE_PATH"] = "GPU"
    os.environ["AMD_OVERLAY_PROFILE"] = "1"
    os.environ["AMD_ABOVE_DIRTY_MODE"] = "EXACT"
    os.environ["AMD_ABOVE_UPLOAD_BUFFER_MODE"] = mode
    os.environ["AMD_FRAME_ACCOUNTING"] = "1"
    print(f"=== RUN {suffix}: AMD_ABOVE_UPLOAD_BUFFER_MODE={mode} ===", flush=True)
    t0 = time.perf_counter()
    result = export_amd_native_d3d11(
        ffmpeg_exe=FFMPEG,
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=2.0,
        video_width=1280,
        video_height=720,
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
    elapsed = time.perf_counter() - t0
    if verify and mode == "DIRECT":
        print(f"[VERIFY] frames_checked={state['frames_checked']} errors={len(state['errors'])}")
        if state["errors"]:
            print("[VERIFY] ERRORS:", state["errors"][:5])
    return out_mp4, result, elapsed


def summarize(result, label: str):
    if not isinstance(result, dict):
        print(f"[BENCH {label}] EXPORT FAILED (returned {result!r})")
        return
    timings = result.get("timings", {})
    keys = ["above_region_to_bytes", "above_upload_buffer_prepare",
            "above_region_upload", "above_exact_crop", "above_total", "producer_prepare"]
    print(f"[BENCH {label}]")
    for k in keys:
        s = timings.get(k)
        if s:
            print(f"  {k:28s} avg={s.get('avg',0):.4f} med={s.get('median',0):.4f} p95={s.get('p95',0):.4f}")
    print(f"  render_fps={result.get('etap8p_a',{}).get('render_fps',0):.3f} "
          f"true_fps={result.get('true_fps',0):.3f}")
    e8n = result.get("etap8n", {})
    print(f"  above_upload_buffer_mode={e8n.get('above_upload_buffer_mode')} "
          f"dirty_mode={e8n.get('above_dirty_mode')}")
    fa = result.get("frame_accounting", {})
    if fa:
        print(f"  frame_accounting: requested={fa.get('requested_frames')} "
              f"decoded={fa.get('decoded_frames')} native_processed={fa.get('native_processed')} "
              f"amf_submitted={fa.get('amf_submitted')} amf_output={fa.get('amf_output')} "
              f"muxed={fa.get('muxed_frames')}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "COPY"
    suffix = sys.argv[2] if len(sys.argv) > 2 else mode.lower()
    verify = "--verify" in sys.argv
    mp4, result, elapsed = run_export(mode, suffix, verify)
    profile_path = Path(str(mp4) + ".amd_profile.json")
    if profile_path.exists():
        profile_path.unlink()
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"[BENCH {suffix}] profile saved to {profile_path}  wall={elapsed:.3f}s")
    summarize(result, suffix)
    print(f"[BENCH {suffix}] mp4={mp4}")
