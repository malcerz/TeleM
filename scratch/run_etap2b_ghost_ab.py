"""ETAP 2B ghosting A/B: canvas-tile equivalence between the ETAP 2A full
upload path and the ETAP 2B dynamic-region path across the needle sweep.

Runs the SAME cand workload twice (340 frames, diagnostics dumps at the
13 sweep frames), once WITHOUT AMD_GAUGE_DYNAMIC_RECTS (2A reference
path) and once WITH it (2B), each in its own CWD so the native
H_hud_canvas_<f>.png dumps land in separate directories.  Compose-probe
artifacts are renamed per mode afterwards.
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
BASE = ROOT / "scratch/etap2b_test"
SWEEP = "100,101,102,103,104,105,150,151,200,201,250,251,320"


def run_mode(mode: str, telemetry, layout) -> Path:
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

    mode_dir = BASE / f"ghost_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    # The exporter's ETAP 2A probe writes to the RELATIVE path
    # scratch/etap2a_test/... -> materialize it under the mode CWD so the
    # artifacts land inside this mode's directory.
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
        os.environ.pop("AMD_PROFILING", None)
        if mode == "2b":
            os.environ["AMD_GAUGE_DYNAMIC_RECTS"] = "444,468,424,360"
            os.environ["AMD_GAUGE_FULL_REFRESH_N"] = "120"
        else:
            os.environ.pop("AMD_GAUGE_DYNAMIC_RECTS", None)
            os.environ.pop("AMD_GAUGE_FULL_REFRESH_N", None)

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
        print(f"[ETAP2B-AB] mode={mode} ok={ok}", flush=True)
    finally:
        os.chdir(old_cwd)

    # Preserve compose-probe artifacts per mode.
    for p in list(probe_src.glob("compose_full_cand_f*.png")) \
            + list(probe_src.glob("gauge_capture_f*.png")) \
            + list(probe_src.glob("gauge_meta_f*.json")):
        dst = mode_dir / p.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(p), str(dst))
    return mode_dir


def main():
    import json as _json

    from src.gui.telemetry_manager import TelemetryDataManager

    with open(PRESET, "r", encoding="utf-8") as f:
        layout = _json.load(f)
    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)

    d2a = run_mode("2a", telemetry, layout)
    d2b = run_mode("2b", telemetry, layout)
    print(f"[ETAP2B-AB] done 2a={d2a} 2b={d2b}", flush=True)


if __name__ == "__main__":
    main()
