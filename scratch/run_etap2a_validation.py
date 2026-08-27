"""AMD ETAP 2A validation runner (AFTER-MAP GPU Speed Gauge).

Variants:
  ref_short   AMD_AFTER_MAP_GAUGE_GPU unset, 340 frames, DIAGNOSTICS ON
              -> legacy BEFORE-MAP gauge + H_hud_canvas_{30,300,900}.png
  cand_short  AMD_AFTER_MAP_GAUGE_GPU=1,    340 frames, DIAGNOSTICS ON
              -> AFTER-MAP gauge + HUD canvas dumps for pre-encode parity
  ref_full    flag unset, full 1131-frame benchmark (profiling ON)
  cand_full   flag=1,     full 1131-frame benchmark (profiling ON)

Usage: python scratch/run_etap2a_validation.py <variant>
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRESET = ROOT / "presets/cycling_dashboard_v10.json"
VIDEO = ROOT / "Video/GX010115.MP4"
FIT = ROOT / "Video/Jazda_na_rowerze_w_porze_lunchu.fit"
OUT_DIR = ROOT / "scratch/etap2a_test"

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "ref_short"
SHORT = VARIANT.endswith("short")
FRAMES = 340 if SHORT else 1131


def main():
    import json
    import shutil

    import src.ffmpeg.amd_native_exporter as _ax  # noqa: F401 (import check)

    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
    from src.gui.telemetry_manager import TelemetryDataManager

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = "cand" if VARIANT.startswith("cand") else "ref"
    suffix = "short" if SHORT else "full"
    out_mp4 = OUT_DIR / f"etap2a_{tag}_{suffix}.mp4"
    log_path = OUT_DIR / f"etap2a_{tag}_{suffix}.log"
    if out_mp4.exists():
        out_mp4.unlink()

    # Fixed workload flags — identical for every variant.
    os.environ["AMD_GPU_MAP_ROTATE"] = "1"
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"

    # The ONLY experimental delta between ref and cand.
    if tag == "cand":
        os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
    else:
        os.environ.pop("AMD_AFTER_MAP_GAUGE_GPU", None)

    if SHORT:
        os.environ["AMD_NATIVE_DIAGNOSTICS"] = "1"
        os.environ.pop("AMD_PROFILING", None)
    else:
        os.environ.pop("AMD_NATIVE_DIAGNOSTICS", None)
        os.environ["AMD_PROFILING"] = "1"

    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)

    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    gps_track = telemetry.get_gps_track_for_source("fit")
    fit_data = telemetry.fit_data

    print(f"[ETAP2A] variant={VARIANT} frames={FRAMES} flag="
          f"{os.environ.get('AMD_AFTER_MAP_GAUGE_GPU', '<unset>')}", flush=True)

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
    print(f"[ETAP2A] done ok={ok} wall={wall:.2f}s out={out_mp4}", flush=True)

    # Collect diagnostic HUD dumps written into CWD by the native layer.
    moved = []
    for fname in ("H_hud_canvas_30.png", "H_hud_canvas_300.png", "H_hud_canvas_900.png"):
        p = Path(fname)
        if p.exists():
            dst = OUT_DIR / f"{tag}_{suffix}_{fname}"
            shutil.move(str(p), str(dst))
            moved.append(dst.name)
    print(f"[ETAP2A] hud_dumps={moved or 'none'}", flush=True)

    # Persist the console transcript for assertion parsing.
    print("[ETAP2A] NOTE: re-run with `python scratch/run_etap2a_validation.py "
          f"{VARIANT} 2>&1 | Tee-Object {log_path}` to capture the log.",
          flush=True)


if __name__ == "__main__":
    main()
