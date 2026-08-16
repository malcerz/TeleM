"""ETAP 5N — microbenchmark: REFERENCE prepare vs PRECOMPUTED hot lookup.

Measures per-frame telemetry cost for all 1131 frames, 5 repetitions.
Reports median / P95 / P99 ms for reference and precomputed lookup,
plus cache build time (separate).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ffmpeg.worker_cache import WORKER_CACHE, init_worker, _resolve_cache_value
from src.gui.layout_manager import resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import (
    build_active_fit_field_plan, prepare_overlay_frame_data,
)
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)
from src.telemetry_precompute import build_telemetry_cache

TARGET_FPS = 30000 / 1001
FRAMES = 1131
REPS = 5


def _setup():
    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    tm = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
    )
    tm.load_gpmf_records(records)
    tm.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    tm.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
    track = tm.track_samples
    gps_track = tm.get_gps_track_for_source(
        layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
    )
    init_worker(
        video_width=3840, video_height=2160, font_path=resolve_font_path("Arial"),
        layout=layout, field_samples={"speed_samples": speed, "track_samples": track,
                                       "alt_samples": altitude},
        max_distance_m=track[-1][1] if track else 0,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
        start_dt_utc=tm.start_dt_utc, tz_offset_hours=2,
        speed_samples=speed, track_samples=track, alt_samples=altitude,
        target_fps=TARGET_FPS, update_rate_step=1, total_overlay_frames=FRAMES,
    )
    plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())
    return tm, layout, speed, altitude, track, gps_track, plan


def main() -> int:
    tm, layout, speed, altitude, track, gps_track, plan = _setup()
    base_dt = tm.start_dt_utc

    cache = build_telemetry_cache(
        layout=layout, base_dt=base_dt, tz_offset_hours=2, start_dt_utc=base_dt,
        speed_samples=speed, track_samples=track, alt_samples=altitude,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=plan,
        total_frames=FRAMES, target_fps=TARGET_FPS,
    )
    print(f"cache build: {cache.build_ms:.1f} ms  mem {cache.memory_bytes/1048576:.3f} MiB",
          flush=True)

    # warm-up
    for f in range(20):
        prepare_overlay_frame_data(
            layout=layout, target_dt=base_dt + timedelta(seconds=f / TARGET_FPS),
            start_dt_utc=base_dt, tz_offset_hours=2, speed_samples=speed,
            track_samples=track, alt_samples=altitude, iso_samples=tm.iso_samples,
            exposure_samples=tm.exposure_samples, temperature_samples=tm.temperature_samples,
            total_frames=FRAMES, current_index=f,
            chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
            resolve_cache_value=_resolve_cache_value,
            gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
            gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
            gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
            gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
            _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=plan,
            resolve_stats=None,
        )

    ref_all: list[float] = []
    pre_all: list[float] = []
    for rep in range(REPS):
        t0 = time.perf_counter()
        for f in range(FRAMES):
            curr_dt = base_dt + timedelta(seconds=f / TARGET_FPS)
            prepare_overlay_frame_data(
                layout=layout, target_dt=curr_dt, start_dt_utc=base_dt, tz_offset_hours=2,
                speed_samples=speed, track_samples=track, alt_samples=altitude,
                iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
                temperature_samples=tm.temperature_samples, total_frames=FRAMES,
                current_index=f, chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
                resolve_cache_value=_resolve_cache_value,
                gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
                gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
                gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
                gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
                _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=plan,
                resolve_stats=None,
            )
        ref_all.append((time.perf_counter() - t0) * 1000.0 / FRAMES)

        t0 = time.perf_counter()
        for f in range(FRAMES):
            cache.lookup(f)
        pre_all.append((time.perf_counter() - t0) * 1000.0 / FRAMES)

    ref_all.sort()
    pre_all.sort()
    print("\n=== MICROBENCH (ms/frame, over full 1131) ===", flush=True)
    for rep in range(REPS):
        print(f"  rep {rep+1}: REF={ref_all[rep]:.4f}  PRE={pre_all[rep]:.4f}", flush=True)
    ref_med = statistics.median(ref_all)
    pre_med = statistics.median(pre_all)
    # P95/P99 across frames: sample per-frame timings on a final pass
    ref_f = []
    pre_f = []
    for f in range(FRAMES):
        curr_dt = base_dt + timedelta(seconds=f / TARGET_FPS)
        t0 = time.perf_counter()
        prepare_overlay_frame_data(
            layout=layout, target_dt=curr_dt, start_dt_utc=base_dt, tz_offset_hours=2,
            speed_samples=speed, track_samples=track, alt_samples=altitude,
            iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples, total_frames=FRAMES,
            current_index=f, chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
            resolve_cache_value=_resolve_cache_value,
            gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
            gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
            gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
            gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
            _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=plan,
            resolve_stats=None,
        )
        ref_f.append((time.perf_counter() - t0) * 1000.0)
        t0 = time.perf_counter()
        cache.lookup(f)
        pre_f.append((time.perf_counter() - t0) * 1000.0)

    def pct(vals, p):
        s = sorted(vals)
        return s[min(len(s) - 1, int(len(s) * p))]

    print(f"  REFERENCE: median={statistics.median(ref_f):.3f} ms "
          f"P95={pct(ref_f, 0.95):.3f} P99={pct(ref_f, 0.99):.3f}", flush=True)
    print(f"  PRECOMPUTED lookup: median={statistics.median(pre_f):.3f} ms "
          f"P95={pct(pre_f, 0.95):.3f} P99={pct(pre_f, 0.99):.3f}", flush=True)
    print(f"  speedup (median): {ref_med / pre_med:.1f}x", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
