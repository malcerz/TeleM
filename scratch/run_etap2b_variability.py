"""AMD ETAP 2B variability measurement run.

Runs the CAND configuration (AFTER-MAP GPU speed gauge ON) for a frame
range with AMD_GAUGE_VARIABILITY_PROBE=1 so the exporter records
per-frame gauge-capture diff statistics into <out>.gauge_variability.json.

Usage: python scratch/run_etap2b_variability.py [frames]
"""
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

FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 350


def main():
    import json

    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
    from src.gui.telemetry_manager import TelemetryDataManager

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_mp4 = OUT_DIR / "var.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
    for suffix in (".amd_profile.json", ".gauge_variability.json"):
        p = Path(str(out_mp4) + suffix)
        if p.exists():
            p.unlink()

    # Fixed workload flags — identical to the ETAP 2A benchmark corpus.
    os.environ["AMD_GPU_MAP_ROTATE"] = "1"
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    # The experimental delta under measurement:
    os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
    # Probe instrumentation (adds numpy diff cost to the producer ONLY):
    os.environ["AMD_GAUGE_VARIABILITY_PROBE"] = "1"
    os.environ.pop("AMD_NATIVE_DIAGNOSTICS", None)
    os.environ.pop("AMD_PROFILING", None)

    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)

    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    gps_track = telemetry.get_gps_track_for_source("fit")
    fit_data = telemetry.fit_data

    print(f"[ETAP2B] variability run frames={FRAMES}", flush=True)

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
    wall = time.perf_counter() - t0
    print(f"[ETAP2B] done ok={ok} wall={wall:.2f}s out={out_mp4}", flush=True)
    print("[ETAP2B] NOTE: re-run with `python scratch/run_etap2b_variability.py "
          f"{FRAMES} 2>&1 | Tee-Object {OUT_DIR / 'var.log'}` to capture the log.",
          flush=True)


if __name__ == "__main__":
    main()
