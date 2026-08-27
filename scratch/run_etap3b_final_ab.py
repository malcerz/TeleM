import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import (
    get_rotation_from_metadata,
    load_json_with_fallback,
    ensure_records_list,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

OUT_DIR = repo_root / "Raporty" / "AMD_ETAP_3B"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH_DIR = repo_root / "scratch" / "etap3b_bench"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_DEF_PATH = repo_root / "def_layout.json"

def run_pipeline(tag: str, layout: dict, frames: int, env_overrides: dict = None) -> dict:
    env_clean = {
        "AMD_NATIVE_DIAGNOSTICS": "0",
        "AMD_NATIVE_PROFILING": "0",
        "AMD_GPU_TIMESTAMP_PROFILE": "0",
        "AMD_NATIVE_FRAME_ACCOUNTING": "0",
        "AMD_AMF_MODE": "ENCODE",
        "AMD_GPU_MAP_ROTATE": "1",
        "AMD_AFTER_MAP_CHART_GPU": "1",
        "AMD_AFTER_MAP_GAUGE_GPU": "1",
        "AMD_LEAN_GPU": "1",
    }
    if env_overrides:
        env_clean.update(env_overrides)
    for k, v in env_clean.items():
        os.environ[k] = str(v)

    tm = TelemetryDataManager()
    processed = read_processed_cache(VIDEO)
    if processed is not None:
        apply_processed_cache(tm, processed)
    else:
        tm.load_gpmf_from_exiftool(VIDEO)
    tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

    records = ensure_records_list(
        load_json_with_fallback(VIDEO.with_suffix(".json"))
    )
    rotation_degrees = get_rotation_from_metadata(records)

    field_samples = {
        "speed_samples": tm.speed_samples,
        "track_samples": tm.track_samples,
        "alt_samples": tm.alt_samples,
        "heading_samples": tm.heading_samples,
        "gpx_heading_samples": tm.gpx_heading_samples,
        "slope_samples": tm.slope_samples,
        "gpx_slope_samples": tm.gpx_slope_samples,
        "iso_samples": tm.iso_samples,
        "exposure_samples": tm.exposure_samples,
        "temperature_samples": tm.temperature_samples,
        "accel_x_samples": tm.accel_x_samples,
        "accel_y_samples": tm.accel_y_samples,
        "accel_z_samples": tm.accel_z_samples,
        "accel_magnitude_samples": tm.accel_magnitude_samples,
        "gyro_x_samples": tm.gyro_x_samples,
        "gyro_y_samples": tm.gyro_y_samples,
        "gyro_z_samples": tm.gyro_z_samples,
        "gyro_magnitude_samples": tm.gyro_magnitude_samples,
    }

    out_file = str(SCRATCH_DIR / f"{tag}_{frames}f.mp4")
    for p in [Path(out_file), Path(out_file + ".amd_profile.json")]:
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    fps = 30000.0 / 1001.0
    print(f"\n{'='*25} RUNNING: {tag} ({frames} frames) {'='*25}", flush=True)
    t0 = time.perf_counter()
    total = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(VIDEO)],
        output_file=out_file,
        duration_s=frames / fps,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        font_path="arial.ttf",
        layout=layout,
        field_samples=field_samples,
        max_distance_m=(tm.track_samples[-1][1] if tm.track_samples else 0),
        target_fps=fps,
        workers=4,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples,
        gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source(
            layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
        ),
        encoder="amd",
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        rotation_degrees=rotation_degrees,
    )
    wall = time.perf_counter() - t0
    print(f"COMPLETED {tag}: total_frames={total}, wall={wall:.3f}s", flush=True)

    prof_p = Path(out_file + ".amd_profile.json")
    prof = json.load(open(prof_p)) if prof_p.exists() else {}
    prof["measured_wall_s"] = wall
    prof["measured_total_frames"] = total
    return prof

def main():
    base_layout = json.load(open(LAYOUT_DEF_PATH, encoding="utf-8"))
    
    results = {}

    # Load baseline REF results from audit
    audit_raw = json.load(open(OUT_DIR / "etap3b_audit_raw.json", encoding="utf-8"))
    results["ref_300f"] = audit_raw["abl_full_300f"]
    results["ref_2001f"] = audit_raw["long_baseline_2001f"]

    # 1. CAND Short Pipeline (300 frames)
    print("\n" + "#" * 80)
    print("STEP 1: CANDIDATE SHORT PIPELINE A/B (300 FRAMES, def_layout, 4K)")
    print("#" * 80)
    prof_cand_300 = run_pipeline("cand_300f", base_layout, 300)
    results["cand_300f"] = prof_cand_300

    # 2. CAND Long Pipeline (2001 frames)
    print("\n" + "#" * 80)
    print("STEP 2: CANDIDATE LONG PIPELINE A/B (2001 FRAMES, def_layout, 4K)")
    print("#" * 80)
    prof_cand_2001 = run_pipeline("cand_2001f", base_layout, 2001)
    results["cand_2001f"] = prof_cand_2001

    with open(OUT_DIR / "etap3b_final_ab_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\nFinal A/B runs completed and saved to Raporty/AMD_ETAP_3B/etap3b_final_ab_results.json")

if __name__ == "__main__":
    main()
