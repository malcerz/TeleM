"""ETAP 5W — memory probe A: Windows metrics + Python object-type deltas
+ referrers (spec 3/5/6).

Per export: Working Set (rss), Private Working Set (uss), Private Bytes
(private), Commit (vms/pagefile), handles, threads, gc object-type snapshot.
Identifies types growing linearly across exports and their referrers.
"""
from __future__ import annotations

import contextlib
import gc
import io
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
FF = r"C:\tools\ffmpeg.exe"

N_EXPORTS = int(os.environ.get("ETAP5W_EXPORTS", "5"))


def _setup_env() -> dict:
    flags = ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
             "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
             "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
             "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
             "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
             "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
             "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS", "AMD_CHART_PATH",
             "AMD_GAUGE_PATH")
    for f in flags:
        os.environ.pop(f, None)
    env = {
        "AMD_MAP_PATH": "GPU", "AMD_MAP_FILTER": "LANCZOS",
        "AMD_COMPOSE_5Q": "OPTIMIZED", "AMD_VP_STATE_MODE": "REFERENCE",
        "AMD_VP_POOL_SIZE": "8", "AMD_CHART_PATH": "GPU_SPLIT",
        "AMD_GAUGE_PATH": "GPU",
    }
    os.environ.update(env)
    return env


def _metrics() -> dict:
    p = psutil.Process()
    m = p.memory_full_info()
    return {
        "ws_rss": m.rss,
        "pws_uss": getattr(m, "uss", 0) or 0,
        "private_bytes": getattr(m, "private", 0) or 0,
        "commit_vms": m.vms,
        "handles": p.num_handles(),
        "threads": p.num_threads(),
    }


def _type_counts() -> Counter:
    gc.collect()
    return Counter(type(o).__name__ for o in gc.get_objects())


def main() -> int:
    env = _setup_env()

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

    def _export(idx: int) -> float:
        mp4 = OUT / f"l5w_probe_{idx}.mp4"
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
        return time.time() - t0

    gc.collect()
    base_metrics = _metrics()
    base_types = _type_counts()

    results = []
    type_log = []
    for idx in range(1, N_EXPORTS + 1):
        m0 = _metrics()
        wall = _export(idx)
        gc.collect()
        m1 = _metrics()
        t1 = _type_counts()
        results.append({
            "export": idx, "wall": wall,
            "before": m0, "after": m1,
            "delta": {k: m1[k] - m0[k] for k in m1},
        })
        type_log.append(t1)
        print(f"exp {idx} wall={wall:.2f}s "
              f"WS {m0['ws_rss']/1e6:.0f}->{m1['ws_rss']/1e6:.0f}MB "
              f"PWS {m0['pws_uss']/1e6:.0f}->{m1['pws_uss']/1e6:.0f}MB "
              f"Priv {m0['private_bytes']/1e6:.0f}->{m1['private_bytes']/1e6:.0f}MB "
              f"Commit {m0['commit_vms']/1e6:.0f}->{m1['commit_vms']/1e6:.0f}MB "
              f"handles {m0['handles']}->{m1['handles']} "
              f"threads {m0['threads']}->{m1['threads']}", flush=True)

    # ── growing types across exports ─────────────────────────────────────
    # per-export type delta after warm-up (export 1 vs base, then steady)
    growing = {}
    for i in range(1, len(type_log)):
        prev = type_log[i - 1]
        cur = type_log[i]
        for typ, cnt in cur.items():
            d = cnt - prev.get(typ, 0)
            if d > 0:
                growing[typ] = growing.get(typ, 0) + d
    # also include the first export vs base
    first = {}
    for typ, cnt in type_log[0].items():
        d = cnt - base_types.get(typ, 0)
        if d > 0:
            first[typ] = first.get(typ, 0) + d
    print("\n=== first-export type deltas (warmup) ===", flush=True)
    for typ, d in sorted(first.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {typ:30s} +{d}", flush=True)
    print("\n=== per-export type deltas (steady, cumulative sum) ===", flush=True)
    for typ, d in sorted(growing.items(), key=lambda kv: -kv[1])[:25]:
        print(f"  {typ:30s} +{d} over {len(type_log)-1} exports", flush=True)

    # ── referrers for top steady-growing types ───────────────────────────
    top_types = [t for t, _ in sorted(growing.items(), key=lambda kv: -kv[1])[:5]]
    referrers = {}
    if top_types:
        objs = [o for o in gc.get_objects() if type(o).__name__ in set(top_types)]
        for typ in top_types:
            samples = [o for o in objs if type(o).__name__ == typ][:10]
            refs = Counter()
            for o in samples:
                for r in gc.get_referrers(o):
                    refs[f"{type(r).__module__}.{type(r).__name__}"] += 1
            referrers[typ] = refs.most_common(5)
        print("\n=== referrers (top holders) ===", flush=True)
        for typ, refs in referrers.items():
            print(f"  {typ}: {refs}", flush=True)

    report = {
        "base_metrics": base_metrics, "results": results,
        "first_export_type_deltas": first, "steady_type_deltas": growing,
        "referrers": referrers,
    }
    (OUT / "etap5w_memprobe.json").write_text(json.dumps(report, indent=2, default=str),
                                              encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5w_memprobe.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
