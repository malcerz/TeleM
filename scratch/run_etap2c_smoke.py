"""AMD ETAP 2C smoke test: AUTO dynamic-region gauge transfer quick check.

Runs the standard workload with AMD_AFTER_MAP_GAUGE_GPU=1 and NO
AMD_GAUGE_DYNAMIC_RECTS (so ETAP 2C AUTO is active), with the in-exporter
region oracle enabled. Asserts from the profile JSON:
  S1. mode == AUTO,
  S2. oracle ran (frames > 0) with missed_dynamic_pixels == 0,
  S3. steady-state region frames occurred (>0),
  S4. first-frame/full resync uploads occurred (>=1).
Usage: python scratch/run_etap2c_smoke.py [frames] [width] [height]
"""
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

FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 40
WIDTH = int(sys.argv[2]) if len(sys.argv) > 2 else 3840
HEIGHT = int(sys.argv[3]) if len(sys.argv) > 3 else 2160
TAG = f"{FRAMES}f_{WIDTH}x{HEIGHT}"

OUT_DIR = ROOT / "scratch/etap2c_test"


def main():
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
    from src.gui.telemetry_manager import TelemetryDataManager

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_mp4 = OUT_DIR / f"smoke_{TAG}.mp4"
    for p in (out_mp4, Path(str(out_mp4) + ".amd_profile.json")):
        if p.exists():
            p.unlink()

    os.environ["AMD_GPU_MAP_ROTATE"] = "1"
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
    # ETAP 2C under test: NO manual rects -> AUTO active by default.
    os.environ.pop("AMD_GAUGE_DYNAMIC_RECTS", None)
    os.environ.pop("AMD_GAUGE_AUTO_REGIONS", None)
    os.environ["AMD_GAUGE_FULL_REFRESH_N"] = "10"
    # In-exporter oracle validator (probe-only cost).
    os.environ["AMD_GAUGE_REGION_ORACLE"] = "1"
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
        video_width=WIDTH,
        video_height=HEIGHT,
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
    print(f"[ETAP2C] smoke {TAG} ok={ok} wall={wall:.2f}s", flush=True)

    prof_path = Path(str(out_mp4) + ".amd_profile.json")
    assert prof_path.exists(), "profile json missing"
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    e2c = prof.get("etap2c_gauge_regions", {})
    print("[ETAP2C] regions:", json.dumps(e2c, indent=None))

    s1 = e2c.get("mode") == "AUTO"
    s2 = (e2c.get("oracle_frames", 0) > 0
          and e2c.get("missed_dynamic_pixels", -1) == 0)
    s3 = e2c.get("oracle_region_frames", 0) > 0
    s4 = e2c.get("oracle_full_frames", 0) >= 1
    print(f"[ETAP2C] GATES S1(mode=AUTO)={s1} S2(oracle_missed=0)={s2} "
          f"S3(region_frames>0)={s3} S4(full_resync>=1)={s4}")
    verdict = ok and s1 and s2 and s3 and s4
    print("ETAP2C SMOKE:", "PASS" if verdict else "FAIL")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
