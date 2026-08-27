"""ETAP 2C benchmark trio (mandated workload): 1131f / GX010115 /
cycling_dashboard_v10 / 3840x2160.

  REF  : AMD_AFTER_MAP_GAUGE_GPU unset (production default, feature OFF)
  FULL : gauge GPU ON + AUTO disabled -> full-tile upload/frame (ETAP 2A)
  AUTO : gauge GPU ON + ETAP 2C AUTO regions (under test)

Writes scratch/etap2c_test/bench_results.json and prints a comparison table.
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
OUT_DIR = ROOT / "scratch/etap2c_test"
TOTAL = 1131


def run_bench(case, telemetry, layout):
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

    out_mp4 = OUT_DIR / f"bench_{case}.mp4"
    prof_path = Path(str(out_mp4) + ".amd_profile.json")
    for p in (out_mp4, prof_path):
        if p.exists():
            p.unlink()
    os.environ["AMD_GPU_MAP_ROTATE"] = "1"
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    os.environ["AMD_PROFILING"] = "1"
    os.environ.pop("AMD_GAUGE_REGION_ORACLE", None)
    os.environ.pop("AMD_GAUGE_DYNAMIC_RECTS", None)
    os.environ.pop("AMD_NATIVE_DIAGNOSTICS", None)
    if case == "REF":
        os.environ.pop("AMD_AFTER_MAP_GAUGE_GPU", None)
        os.environ.pop("AMD_GAUGE_AUTO_REGIONS", None)
    elif case == "FULL":
        os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
        os.environ["AMD_GAUGE_AUTO_REGIONS"] = "0"
    else:
        os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
        os.environ.pop("AMD_GAUGE_AUTO_REGIONS", None)

    print(f"\n===== BENCH {case} ({TOTAL}f 4K) =====", flush=True)
    t0 = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=TOTAL / 59.94005994,
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
    wall = time.perf_counter() - t0
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    summ = prof.get("etap8pa_summary", prof.get("timings", {}))
    ts = prof.get("timings", {})
    e5l = prof.get("etap5l", {})
    row = {
        "ok": bool(ok),
        "wall_s": round(wall, 2),
        "render_fps": summ.get("render_fps"),
        "user_effective_fps": summ.get("user_effective_fps"),
        "mode": prof.get("etap2c_gauge_regions", {}).get("mode"),
        "above_total_avg": (ts.get("above_total", {}) or {}).get("avg_ms"),
        "compose_avg": (ts.get("compose_overlay", {}) or {}).get("avg_ms"),
        "gauge_tobytes_avg": (ts.get("gauge_tobytes", {}) or {}).get("avg_ms"),
        "gauge_upload_avg": (ts.get("gauge_upload", {}) or {}).get("avg_ms"),
        "pipeline_total_avg": (ts.get("pipeline_total", {})
                               or {}).get("avg_ms"),
        "consumer_native_avg": (ts.get("consumer_native_call", {})
                                or {}).get("avg_ms"),
        "region_frames": e5l.get("etap2b_gauge_region_upload_frames"),
        "full_frames": e5l.get("etap2b_gauge_full_upload_frames"),
        "bytes_per_frame": ts.get("gauge_bytes_per_frame", {}),
    }
    print(f"[BENCH] {case}: {json.dumps(row)}", flush=True)
    return row


def main():
    from src.gui.telemetry_manager import TelemetryDataManager

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)
    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)

    rows = {c: run_bench(c, telemetry, layout)
            for c in ("REF", "FULL", "AUTO")}
    (OUT_DIR / "bench_results.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8")
    hdr = ("case", "render_fps", "user_fps", "above_tot", "tobytes",
           "upload", "mode")
    print(f"\n{hdr[0]:6} {hdr[1]:>10} {hdr[2]:>9} {hdr[3]:>10} "
          f"{hdr[4]:>8} {hdr[5]:>8} {hdr[6]:>13}")
    for c, r in rows.items():
        ue = r.get("user_effective_fps")
        print(f"{c:6} {r.get('render_fps')!s:>10} "
              f"{ue if ue is not None else '-':>9} "
              f"{r.get('above_total_avg')!s:>10} "
              f"{r.get('gauge_tobytes_avg')!s:>8} "
              f"{r.get('gauge_upload_avg')!s:>8} {r.get('mode')!s:>13}")
    print("[BENCH] saved -> scratch/etap2c_test/bench_results.json")


if __name__ == "__main__":
    main()
