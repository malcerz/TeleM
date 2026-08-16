"""ETAP 5Q — microbench REFERENCE vs OPTIMIZED compose (spec section 13).

5 cold repetitions over the 1131 real frames, production config
(GPU_SPLIT charts + GPU gauge capture).  Caches cleared between reps so each
rep is a cold run like production.  Reports per-mode median / P95 / P99 / avg
and the saving (ms and %).
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
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import (
    build_active_fit_field_plan, prepare_overlay_frame_data,
)
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)

TARGET_FPS = 30000 / 1001
W, H = 3840, 2160
CHART_SLOTS = {"fit_cadence_text": 0, "fit_heart_rate_text": 1}
GAUGE_KEY = "fit_enhanced_speed_text"


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
        video_width=W, video_height=H, font_path=resolve_font_path("Arial"),
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
        target_fps=TARGET_FPS, update_rate_step=1, total_overlay_frames=1131,
    )
    fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())
    return tm, layout, speed, altitude, track, gps_track, fit_field_plan


def _make_frame_data_fn(tm, layout, speed, altitude, track, gps_track, fit_field_plan):
    base_dt = tm.start_dt_utc

    def fd(frame_idx):
        curr_dt = base_dt + timedelta(seconds=frame_idx / TARGET_FPS)
        return prepare_overlay_frame_data(
            layout=layout, target_dt=curr_dt, start_dt_utc=base_dt, tz_offset_hours=2,
            speed_samples=speed, track_samples=track, alt_samples=altitude,
            iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples, total_frames=1131,
            current_index=frame_idx, chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
            resolve_cache_value=_resolve_cache_value,
            gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
            gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
            gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
            gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
            _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=fit_field_plan,
            resolve_stats={"calls": 0, "per_field": {}},
        )
    return fd


def _clear_caches():
    from src.indicators.helpers import _STATIC_CACHE
    from src.indicators.chart import _FINAL_STATIC_CHART_CACHE
    from src.indicators.chart_utils import _CHART_BG_CACHE
    from src.indicators.rotated_paste import _WIDGET_ALPHA_MIN
    _STATIC_CACHE.clear()
    _FINAL_STATIC_CHART_CACHE.clear()
    _CHART_BG_CACHE.clear()
    _WIDGET_ALPHA_MIN.clear()


def main() -> int:
    import src.indicators.helpers as helpers
    mode = sys.argv[1].strip().upper() if len(sys.argv) > 1 else "REFERENCE"
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    assert mode in ("REFERENCE", "OPTIMIZED")

    print(f"=== ETAP 5Q MICROBENCH: {mode} ({reps} cold reps x 1131 frames) ===", flush=True)
    tm, layout, speed, altitude, track, gps_track, plan = _setup()
    font_path = resolve_font_path("Arial")
    fd = _make_frame_data_fn(tm, layout, speed, altitude, track, gps_track, plan)

    helpers._COMPOSE_5Q = (mode == "OPTIMIZED")
    all_times = []
    for rep in range(reps):
        _clear_caches()
        rep_times = []
        for f in range(1131):
            kw = fd(f)
            bboxes = {}
            cap = {}
            t0 = time.perf_counter()
            compose_overlay(
                canvas_w=W, canvas_h=H, layout=layout, font_path=font_path,
                _bboxes=bboxes,
                gpu_capture_keys=set(CHART_SLOTS.keys()) | {GAUGE_KEY},
                gpu_capture=cap,
                split_chart_keys=set(CHART_SLOTS.keys()),
                **kw,
            )
            rep_times.append((time.perf_counter() - t0) * 1000.0)
        all_times.append(rep_times)
        srt = sorted(rep_times)
        print(f"  rep {rep}: med={statistics.median(rep_times):.3f} "
              f"p95={srt[int(0.95*len(srt))-1]:.3f} p99={srt[int(0.99*len(srt))-1]:.3f} "
              f"avg={sum(rep_times)/len(rep_times):.3f} ms/frame "
              f"({sum(rep_times)/1000:.2f} s total)", flush=True)

    # aggregate across reps: pool all per-frame times
    pooled = [t for rt in all_times for t in rt]
    srt = sorted(pooled)
    med = statistics.median(pooled)
    p95 = srt[int(0.95 * len(srt)) - 1]
    p99 = srt[int(0.99 * len(srt)) - 1]
    avg = sum(pooled) / len(pooled)
    print(f"\n{mode} AGG ({len(pooled)} samples): med={med:.3f} p95={p95:.3f} "
          f"p99={p99:.3f} avg={avg:.3f} ms/frame", flush=True)

    out = {
        "mode": mode, "reps": reps, "frames": 1131,
        "samples": len(pooled),
        "median_ms": med, "p95_ms": p95, "p99_ms": p99, "avg_ms": avg,
    }
    path = ROOT / "Raporty" / "AMD_ETAP5G" / f"etap5q_microbench_{mode.lower()}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  saved: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
