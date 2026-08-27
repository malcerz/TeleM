"""AMD ETAP 2B smoke test: dynamic-region gauge transfer quick check."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRESET = ROOT / "presets/cycling_dashboard_v10.json"
VIDEO = ROOT / "Video/GX010115.MP4"
FIT = ROOT / "Video/Jazda_na_rowerze_w_porze_lunchu.fit"
OUT_DIR = ROOT / "scratch/etap2b_test"

FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def main():
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
    from src.gui.telemetry_manager import TelemetryDataManager

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_mp4 = OUT_DIR / "smoke.mp4"
    for p in (out_mp4, Path(str(out_mp4) + ".amd_profile.json")):
        if p.exists():
            p.unlink()

    os.environ["AMD_GPU_MAP_ROTATE"] = "1"
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
    # ETAP 2B under test:
    os.environ["AMD_GAUGE_DYNAMIC_RECTS"] = "444,468,424,360"
    os.environ["AMD_GAUGE_FULL_REFRESH_N"] = "10"
    os.environ.pop("AMD_NATIVE_DIAGNOSTICS", None)
    os.environ.pop("AMD_PROFILING", None)

    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)

    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    gps_track = telemetry.get_gps_track_for_source("fit")
    fit_data = telemetry.fit_data

    t0 = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=FRAMES / 59.94005994,
        video_width=3840,
        video_height=2160,
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
        field_samples=fit_data,
        fit_data=fit_data,
        gps_track=gps_track,
        target_fps=59.94005994,
        video_bitrate="40M",
        quality="speed",
    )
    print(f"[ETAP2B] smoke ok={ok} wall={time.perf_counter()-t0:.2f}s", flush=True)

    prof_path = Path(str(out_mp4) + ".amd_profile.json")
    if prof_path.exists():
        prof = json.loads(prof_path.read_text(encoding="utf-8"))
        e5l = prof.get("etap5l", {})
        ts = prof.get("timings", {})
        print("[ETAP2B] gauge_gpu_frames=", e5l.get("gauge_gpu_frames"),
              " region_frames=", e5l.get("etap2b_gauge_region_upload_frames"),
              " full_frames=", e5l.get("etap2b_gauge_full_upload_frames"),
              " calls=", e5l.get("etap2b_gauge_upload_calls_total"))
        for k in ("gauge_tobytes", "gauge_capture", "gauge_diff",
                  "gauge_bytes_per_frame", "gauge_upload", "gauge_upload_calls"):
            s = ts.get(k, {})
            print(f"[ETAP2B] {k}: avg={s.get('avg_ms', s.get('avg'))} "
                  f"med={s.get('median_ms', s.get('median'))} "
                  f"p95={s.get('p95_ms', s.get('p95'))}")


if __name__ == "__main__":
    main()
