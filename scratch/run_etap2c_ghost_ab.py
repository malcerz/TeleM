"""ETAP 2C ghosting/parity A/B: FULL-TILE reference vs AUTO region transfer.

Runs the SAME workload twice (340 frames, diagnostics dumps at 13 needle
sweep frames), once with ETAP 2C AUTO disabled (FULL_TILE every frame ==
validated ETAP 2A behavior) and once with AUTO active. Artifacts land in
per-mode CWDs (the exporter probe writes relative scratch/etap2a_test/...).

Gates checked afterwards by scratch/check_etap2c_ghost_equivalence.py:
  G1. canvas gauge tile bit-exact between both modes on every sweep frame;
  G2. oracle (in-run) missed_dynamic_pixels == 0 for the AUTO run;
  G3. tile bbox stable across sweep; art varies.
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRESET = ROOT / "presets/cycling_dashboard_v10.json"
VIDEO = ROOT / "Video/GX010115.MP4"
FIT = ROOT / "Video/Jazda_na_rowerze_w_porze_lunchu.fit"
BASE = ROOT / "scratch/etap2c_test"
SWEEP = "100,101,102,103,104,105,150,151,200,201,250,251,320"


def run_mode(mode: str, telemetry, layout) -> Path:
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

    mode_dir = BASE / f"ghost_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    # The exporter's ETAP 2A probe writes to the RELATIVE path
    # scratch/etap2a_test/... -> materialize it under the mode CWD.
    probe_src = mode_dir / "scratch" / "etap2a_test"
    probe_src.mkdir(parents=True, exist_ok=True)
    old_cwd = os.getcwd()
    os.chdir(mode_dir)
    try:
        os.environ["AMD_GPU_MAP_ROTATE"] = "1"
        os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
        os.environ["AMD_MAP_PATH"] = "GPU"
        os.environ["AMD_MAP_FILTER"] = "BICUBIC"
        os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
        os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
        os.environ["AMD_ETAP2A_COMPOSE_PROBE"] = "cand"
        os.environ["AMD_HUD_DUMP_FRAMES"] = SWEEP
        os.environ["AMD_NATIVE_DIAGNOSTICS"] = "1"
        os.environ["AMD_GAUGE_REGION_ORACLE"] = "1"
        os.environ.pop("AMD_PROFILING", None)
        os.environ.pop("AMD_GAUGE_DYNAMIC_RECTS", None)
        if mode == "full":
            # Reference: full-tile upload every frame (ETAP 2A semantics).
            os.environ["AMD_GAUGE_AUTO_REGIONS"] = "0"
        else:
            # Under test: AUTO regions active (default).
            os.environ.pop("AMD_GAUGE_AUTO_REGIONS", None)

        ok = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(VIDEO)],
            output_file=str(mode_dir / "ghost.mp4"),
            duration_s=340 / 59.94005994,
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
        print(f"[ETAP2C-AB] mode={mode} ok={ok}", flush=True)
    finally:
        os.chdir(old_cwd)

    # Preserve probe artifacts per mode.
    for pat in ("compose_full_cand_f*.png", "gauge_capture_f*.png",
                "gauge_meta_f*.json", "H_hud_canvas_*.png"):
        for p in probe_src.glob(pat):
            dst = mode_dir / p.name
            if dst.exists():
                dst.unlink()
            shutil.move(str(p), str(dst))
    return mode_dir


def main():
    from src.gui.telemetry_manager import TelemetryDataManager

    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)
    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)

    dfull = run_mode("full", telemetry, layout)
    dauto = run_mode("auto", telemetry, layout)
    print(f"[ETAP2C-AB] done full={dfull} auto={dauto}", flush=True)


if __name__ == "__main__":
    main()
