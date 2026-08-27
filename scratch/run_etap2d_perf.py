"""ETAP 2D performance smoke: default config (post-flip) vs ETAP 2C baseline.

Mandated workload family: GX010115 / cycling_dashboard_v10 / 3840x2160 /
AMD_NATIVE_D3D11. Runs >=300 frames with ZERO gauge env vars (production
default after the 2D flip) and prints RENDER FPS, above_total,
producer_prepare, gauge_tobytes/gauge_upload and gauge bytes/frame next to
the ETAP 2C AUTO reference numbers:
    render_fps 35.965 | above_total 13.90 ms | median bytes/frame 329780

Usage: python scratch/run_etap2d_perf.py [frames=300]
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
OUT_DIR = ROOT / "scratch/etap2d_test"

# ETAP 2C bench AUTO reference (1131f, same workload family).
BASELINE = {"render_fps": 35.965, "above_total_avg_ms": 13.90,
            "bytes_frame_median": 329780}


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_mp4 = OUT_DIR / f"perf_{frames}f.mp4"
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
    # Production default config: NO gauge env at all.
    for var in ("AMD_AFTER_MAP_GAUGE_GPU", "AMD_GAUGE_AUTO_REGIONS",
                "AMD_GAUGE_DYNAMIC_RECTS", "AMD_GAUGE_REGION_ORACLE",
                "AMD_GAUGE_FULL_REFRESH_N"):
        os.environ.pop(var, None)

    with open(PRESET, "r", encoding="utf-8") as fh:
        layout = json.load(fh)
    from src.gui.telemetry_manager import TelemetryDataManager
    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)

    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
    t0 = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=frames / 59.94005994,
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
    assert prof_path.exists(), "profile json missing"
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    summ = prof.get("etap8pa_summary", {})
    ts = prof.get("timings", {})
    e5l = prof.get("etap5l", {})
    row = {
        "ok": bool(ok),
        "frames": frames,
        "wall_s": round(wall, 2),
        "render_fps": summ.get("render_fps"),
        "user_effective_fps": summ.get("user_effective_fps"),
        "mode": prof.get("etap2c_gauge_regions", {}).get("mode"),
        "above_total_avg_ms": (ts.get("above_total", {}) or {}).get("avg_ms"),
        "producer_prepare_avg_ms": (ts.get("producer_prepare", {})
                                    or {}).get("avg_ms"),
        "gauge_tobytes_avg_ms": (ts.get("gauge_tobytes", {})
                                 or {}).get("avg_ms"),
        "gauge_upload_avg_ms": (ts.get("gauge_upload", {})
                                or {}).get("avg_ms"),
        "pipeline_total_avg_ms": (ts.get("pipeline_total", {})
                                  or {}).get("avg_ms"),
        "region_frames": e5l.get("etap2b_gauge_region_upload_frames"),
        "full_frames": e5l.get("etap2b_gauge_full_upload_frames"),
        "bytes_per_frame": ts.get("gauge_bytes_per_frame", {}),
    }
    print("[ETAP2D-PERF] " + json.dumps(row))
    print(f"[ETAP2D-PERF] baseline(2C AUTO 1131f): {BASELINE}")
    gates = {
        "export_ok": bool(ok),
        "mode_auto": row["mode"] == "AUTO",
        "region_frames_pos": (row["region_frames"] or 0) > 0,
    }
    fps = row.get("render_fps")
    if isinstance(fps, (int, float)) and fps > 0:
        row["fps_delta_vs_baseline_pct"] = round(
            100.0 * (fps - BASELINE["render_fps"])
            / BASELINE["render_fps"], 2)
    at = row.get("above_total_avg_ms")
    if isinstance(at, (int, float)) and at > 0:
        row["above_total_delta_vs_baseline_ms"] = round(
            at - BASELINE["above_total_avg_ms"], 3)
    print("[ETAP2D-PERF] hard gates: " + json.dumps(gates))
    (OUT_DIR / f"perf_{frames}f_results.json").write_text(
        json.dumps({"row": row, "gates": gates}, indent=2),
        encoding="utf-8")
    print("ETAP2D PERF:", "PASS" if all(gates.values()) else "FAIL")
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
