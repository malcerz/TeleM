"""ETAP 5W — 20-export memory soak (spec 16/17/18).

20 full 1131-frame exports in one process, pool 8.  First 10 with
AMD_COMPOSE_5Q=REFERENCE, second 10 with OPTIMIZED.  After every export +
destroy + gc we record: Private Bytes, Working Set, Private Working Set,
Commit, live Python objects, handles, threads, and cache sizes.  Trend over
exports 5..20 classifies PLATEAU/BOUNDED vs LINEAR GROWTH.
"""
from __future__ import annotations

import contextlib
import gc
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scratch"))
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
FF = r"C:\tools\ffmpeg.exe"
N_EXPORTS = 20


def _setup_env() -> None:
    flags = ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
             "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
             "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
             "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
             "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
             "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
             "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS", "AMD_CHART_PATH",
             "AMD_GAUGE_PATH", "AMD_DEBUG_NO_AMF", "AMD_DEBUG_NO_MF", "AMD_DEBUG_NO_VP")
    for f in flags:
        os.environ.pop(f, None)
    os.environ.update({
        "AMD_MAP_PATH": "GPU", "AMD_MAP_FILTER": "LANCZOS",
        "AMD_VP_STATE_MODE": "REFERENCE", "AMD_VP_POOL_SIZE": "8",
        "AMD_POOL_LIFECYCLE_STATS": "1", "AMD_CHART_PATH": "GPU_SPLIT",
        "AMD_GAUGE_PATH": "GPU",
    })


def _metrics() -> dict:
    p = psutil.Process()
    m = p.memory_full_info()
    return {
        "private_bytes": getattr(m, "private", 0) or 0,
        "ws_rss": m.rss,
        "pws_uss": getattr(m, "uss", 0) or 0,
        "commit_vms": m.vms,
        "handles": p.num_handles(),
        "threads": p.num_threads(),
    }


def _cache_sizes() -> dict:
    try:
        from src.indicators import helpers
        from src.indicators import chart_utils
        from src.indicators import chart
        return {
            "static_cache": len(helpers._STATIC_CACHE),
            "font_cache": len(helpers.FONT_CACHE),
            "chart_bg_cache": len(chart_utils._CHART_BG_CACHE),
            "final_static_chart": len(chart._FINAL_STATIC_CHART_CACHE),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def main() -> int:
    _setup_env()

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

    def _export(idx: int) -> dict:
        os.environ["AMD_COMPOSE_5Q"] = "REFERENCE" if idx <= 10 else "OPTIMIZED"
        mp4 = OUT / f"l5w_soak_{idx:02d}.mp4"
        buf = io.StringIO()
        t0 = time.time()
        with contextlib.redirect_stdout(buf):
            stream_overlay_to_ffmpeg(
                ffmpeg_exe=FF, input_files=[str(video)], output_file=str(mp4),
                duration_s=1131 * (1001.0 / 30000.0),
                start_dt_utc=telemetry.start_dt_utc, tz_offset_hours=2,
                speed_samples=speed, track_samples=track, alt_samples=altitude,
                font_path=resolve_font_path("Arial"), layout=layout,
                field_samples={"speed_samples": speed, "track_samples": track,
                               "alt_samples": altitude},
                max_distance_m=track[-1][1] if track else 0,
                target_fps=30000 / 1001, update_rate_step=1, workers=1,
                iso_samples=telemetry.iso_samples,
                exposure_samples=telemetry.exposure_samples,
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
        out = buf.getvalue()
        lifecycle = None
        m = re.search(r"\[VP POOL\] lifecycle: ([^\n]+)", out)
        if m:
            lifecycle = m.group(1)
        return {"wall": wall, "lifecycle": lifecycle}

    gc.collect()
    base = _metrics()
    base_cache = _cache_sizes()
    base_objs = len(gc.get_objects())
    entries = []
    for idx in range(1, N_EXPORTS + 1):
        res = _export(idx)
        gc.collect()
        m = _metrics()
        objs = len(gc.get_objects())
        cache = _cache_sizes()
        live = None
        if res["lifecycle"]:
            tm = re.search(r"textures created=\d+ released=\d+ live=(\d+)", res["lifecycle"])
            vm = re.search(r"views created=\d+ released=\d+ live=(\d+)", res["lifecycle"])
            live = (int(tm.group(1)) if tm else None, int(vm.group(1)) if vm else None)
        entry = {
            "export": idx, "compose": "REFERENCE" if idx <= 10 else "OPTIMIZED",
            "wall": res["wall"], "metrics": m, "objects": objs, "cache": cache,
            "native_live": live,
        }
        entries.append(entry)
        print(f"soak {idx:02d} {entry['compose'][:4]} wall={res['wall']:.2f}s "
              f"Priv {m['private_bytes']/1e6:6.0f} WS {m['ws_rss']/1e6:6.0f} "
              f"Commit {m['commit_vms']/1e6:6.0f}MB objs {objs} "
              f"handles {m['handles']} threads {m['threads']} "
              f"static_cache {cache.get('static_cache')} live {live}", flush=True)

    # trend classification on exports 5..20 (Private Bytes per export delta)
    priv = [e["metrics"]["private_bytes"] for e in entries[4:]]
    deltas = [priv[i] - priv[i - 1] for i in range(1, len(priv))]
    slope = (priv[-1] - priv[0]) / max(1, len(priv) - 1)
    last_half = priv[len(priv) // 2:]
    growth_last_half = last_half[-1] - last_half[0]
    classification = "PLATEAU/BOUNDED" if growth_last_half < 150e6 else "LINEAR_GROWTH"
    report = {
        "base_metrics": base, "base_cache": base_cache, "base_objects": base_objs,
        "entries": entries,
        "trend": {
            "private_bytes_exports_5_20": [x / 1e6 for x in priv],
            "slope_mb_per_export": slope / 1e6,
            "growth_last_half_mb": growth_last_half / 1e6,
            "classification": classification,
        },
    }
    (OUT / "etap5w_soak.json").write_text(json.dumps(report, indent=2, default=str),
                                          encoding="utf-8")
    print(f"\nCLASSIFICATION: {classification} "
          f"(priv {priv[0]/1e6:.0f}->{priv[-1]/1e6:.0f}MB, slope {slope/1e6:+.1f}MB/exp, "
          f"last-half growth {growth_last_half/1e6:+.0f}MB)", flush=True)
    print(f"JSON: {OUT / 'etap5w_soak.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
