"""ETAP 5V — memory probe: is the soak working-set growth a real leak or just
Python allocator retention?

4 full exports in one process; after each: gc.collect(), measure RSS and the
number of live tracked objects.  If RSS stabilizes after gc and object count
does not keep growing -> allocator retention (no leak).  If object count grows
monotonically -> real reference leak to investigate.
"""
from __future__ import annotations

import contextlib
import gc
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
FF = r"C:\tools\ffmpeg.exe"


def _setup_env() -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
                 "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS", "AMD_CHART_PATH",
                 "AMD_GAUGE_PATH"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    env["AMD_VP_POOL_SIZE"] = "8"
    env["AMD_CHART_PATH"] = "GPU_SPLIT"
    env["AMD_GAUGE_PATH"] = "GPU"
    return env


def main() -> int:
    env = _setup_env()
    os.environ.update(env)

    from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
    from src.gui.layout_manager import resolve_font_path
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_extract import (
        ensure_records_list, extract_speed_samples, extract_altitude_samples,
        extract_track_samples, extract_iso_samples, extract_exposure_samples,
        extract_temperature_samples, smooth_speed_samples, interpolate_value,
        load_json_with_fallback,
    )

    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
    )
    telemetry.load_gpmf_records(records)
    telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
    with (ROOT / "def_layout.json").open(encoding="utf-8") as handle:
        layout = json.load(handle)
    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    video = ROOT / "Video" / "GX020079.mp4"

    def _rss():
        return psutil.Process().memory_info().rss

    def _objs():
        gc.collect()
        return len(gc.get_objects())

    gc.collect()
    base_rss = _rss()
    base_objs = _objs()
    results = []
    for idx in range(1, 5):
        mp4 = OUT / f"l5v_mem_{idx}.mp4"
        buf = io.StringIO()
        t0 = time.time()
        with contextlib.redirect_stdout(buf):
            result = stream_overlay_to_ffmpeg(
                ffmpeg_exe=FF, input_files=[str(video)], output_file=str(mp4),
                duration_s=1131 * (1001.0 / 30000.0),
                start_dt_utc=telemetry.start_dt_utc, tz_offset_hours=2,
                speed_samples=speed, track_samples=track, alt_samples=altitude,
                font_path=resolve_font_path("Arial"), layout=layout,
                field_samples={"speed_samples": speed, "track_samples": track,
                               "alt_samples": altitude},
                max_distance_m=track[-1][1] if track else 0,
                target_fps=30000 / 1001, update_rate_step=1, workers=1,
                iso_samples=telemetry.iso_samples, exposure_samples=telemetry.exposure_samples,
                temperature_samples=telemetry.temperature_samples,
                gpx_speed_samples=telemetry.gpx_speed_samples,
                gpx_track_samples=telemetry.gpx_track_samples,
                gpx_alt_samples=telemetry.gpx_alt_samples,
                gpx_power_samples=telemetry.gpx_power_samples,
                gpx_atemp_samples=telemetry.gpx_atemp_samples,
                gpx_hr_samples=telemetry.gpx_hr_samples,
                gpx_cad_samples=telemetry.gpx_cad_samples,
                fit_data=telemetry.fit_data,
                gps_track=telemetry.get_gps_track_for_source(
                    layout.get("indicators", {}).get("track_map", {}).get("source", "fit")),
                encoder="amd", gpu=0, video_bitrate="40M", render_w=3840, render_h=2160,
                resolution_name="source", rotation_degrees=180, container_rotation=180,
                overlay_w=1920, overlay_h=1080,
            )
        wall = time.time() - t0
        # GC + measure after the export fully returns
        gc.collect()
        rss = _rss()
        objs = _objs()
        results.append({
            "export": idx, "wall": wall, "result": result,
            "rss_after_gc": rss, "rss_delta_vs_prev": rss - (results[-1]["rss_after_gc"] if results else base_rss),
            "live_objects_after_gc": objs,
            "obj_delta_vs_prev": objs - (results[-1]["live_objects_after_gc"] if results else base_objs),
        })
        print(f"exp {idx} wall={wall:.2f}s rss={rss/1e6:.1f}MB "
              f"(delta {results[-1]['rss_delta_vs_prev']/1e6:+.1f}MB) "
              f"objs={objs} (delta {results[-1]['obj_delta_vs_prev']:+d})", flush=True)
    report = {
        "base_rss": base_rss, "base_objs": base_objs, "results": results,
        "rss_growth_4_exports": results[-1]["rss_after_gc"] - base_rss,
        "obj_growth_4_exports": results[-1]["live_objects_after_gc"] - base_objs,
    }
    (OUT / "etap5v_memprobe.json").write_text(json.dumps(report, indent=2, default=str),
                                              encoding="utf-8")
    print(f"\nRSS growth (gc'd, 4 exports): {report['rss_growth_4_exports']/1e6:.1f}MB "
          f"| live objects growth: {report['obj_growth_4_exports']:+d}", flush=True)
    print(f"JSON: {OUT / 'etap5v_memprobe.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
