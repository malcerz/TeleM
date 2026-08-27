"""ETAP 2C mode-selection matrix (short E2E runs).

  T1 default (no env):            mode == AUTO
  T2 AMD_GAUGE_DYNAMIC_RECTS set: mode == MANUAL_RECTS  (env wins over AUTO)
  T3 AMD_GAUGE_AUTO_REGIONS=0:    mode == FULL_TILE     (AUTO disabled)
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRESET = ROOT / "presets/cycling_dashboard_v10.json"
VIDEO = ROOT / "Video/GX010115.MP4"
FIT = ROOT / "Video/Jazda_na_rowerze_w_porze_lunchu.fit"
OUT_DIR = ROOT / "scratch/etap2c_test"
FRAMES = 12


def run_case(case, telemetry, layout):
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

    out_mp4 = OUT_DIR / f"mode_{case}.mp4"
    prof_path = Path(str(out_mp4) + ".amd_profile.json")
    for p in (out_mp4, prof_path):
        if p.exists():
            p.unlink()
    os.environ["AMD_GPU_MAP_ROTATE"] = "1"
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
    os.environ.pop("AMD_GAUGE_REGION_ORACLE", None)
    os.environ.pop("AMD_NATIVE_DIAGNOSTICS", None)
    os.environ.pop("AMD_PROFILING", None)
    if case == "manual":
        os.environ["AMD_GAUGE_DYNAMIC_RECTS"] = "444,468,424,360"
        os.environ.pop("AMD_GAUGE_AUTO_REGIONS", None)
    elif case == "autooff":
        os.environ.pop("AMD_GAUGE_DYNAMIC_RECTS", None)
        os.environ["AMD_GAUGE_AUTO_REGIONS"] = "0"
    else:
        os.environ.pop("AMD_GAUGE_DYNAMIC_RECTS", None)
        os.environ.pop("AMD_GAUGE_AUTO_REGIONS", None)

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
        field_samples=telemetry.fit_data,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        target_fps=59.94005994,
        video_bitrate="40M",
        quality="speed",
    )
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    mode = prof.get("etap2c_gauge_regions", {}).get("mode")
    print(f"[MATRIX] case={case} ok={ok} mode={mode}", flush=True)
    return ok, mode


def main():
    from src.gui.telemetry_manager import TelemetryDataManager

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)
    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)

    results = {}
    for case in ("auto", "manual", "autooff"):
        results[case] = run_case(case, telemetry, layout)

    t1 = results["auto"] == (True, "AUTO")
    t2 = results["manual"] == (True, "MANUAL_RECTS")
    t3 = results["autooff"] == (True, "FULL_TILE")
    print(f"[MATRIX] T1(default->AUTO)={t1} "
          f"T2(rects win -> MANUAL_RECTS)={t2} "
          f"T3(auto disabled -> FULL_TILE)={t3}")
    verdict = t1 and t2 and t3
    print("ETAP2C MODE MATRIX:", "PASS" if verdict else "FAIL")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
