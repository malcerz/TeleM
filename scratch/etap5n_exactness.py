"""ETAP 5N — value/type exactness gate: REFERENCE vs PRECOMPUTED telemetry.

Compares, for all 1131 frames and ALL fields returned by
prepare_overlay_frame_data, the reference path against the precomputed cache
lookup.  Also runs the boundary/NONE frame set and an alternate-layout check.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
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


def _setup(extra_fit=None):
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
    if extra_fit:
        # alternate-layout: enable an extra FIT field
        layout["indicators"][extra_fit] = {"enabled": True, "form": "text"}
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
        target_fps=TARGET_FPS, update_rate_step=1, total_overlay_frames=1131,
    )
    fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())
    return tm, layout, speed, altitude, track, gps_track, fit_field_plan


def _reference_kwargs(tm, layout, speed, altitude, track, gps_track, fit_field_plan, frame_idx):
    base_dt = tm.start_dt_utc
    curr_dt = base_dt + __import__("datetime").timedelta(seconds=frame_idx / TARGET_FPS)
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
        resolve_stats=None,
    )


def _build_cache(tm, layout, speed, altitude, track, gps_track, fit_field_plan):
    return build_telemetry_cache(
        layout=layout, base_dt=tm.start_dt_utc, tz_offset_hours=2,
        start_dt_utc=tm.start_dt_utc, speed_samples=speed, track_samples=track,
        alt_samples=altitude, iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples, temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=fit_field_plan,
        total_frames=1131, target_fps=TARGET_FPS,
    )


def _diff(rec: dict, pre: dict):
    """Deep compare type+value. Return (mismatches, max_num_diff)."""
    mismatches = []
    max_num = 0.0
    for k in rec.keys():
        a, b = rec[k], pre[k]
        if type(a) is not type(b):
            mismatches.append((k, a, b, "TYPE"))
            continue
        if isinstance(a, dict):
            if a != b:
                mismatches.append((k, a, b, "DICT"))
            for kk in a:
                if isinstance(a[kk], (int, float)) and not isinstance(a[kk], bool):
                    try:
                        max_num = max(max_num, abs(a[kk] - b[kk]))
                    except (TypeError, KeyError):
                        pass
        elif isinstance(a, (list, tuple)):
            if a != b:
                mismatches.append((k, a, b, "LIST"))
        elif isinstance(a, datetime):
            if a != b:
                mismatches.append((k, a, b, "DT"))
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            if a != b:
                mismatches.append((k, a, b, "NUM"))
            max_num = max(max_num, abs(a - b))
        else:
            if a != b:
                mismatches.append((k, a, b, "VAL"))
    return mismatches, max_num


def main() -> int:
    print("=== ETAP 5N EXACTNESS GATE ===", flush=True)
    tm, layout, speed, altitude, track, gps_track, plan = _setup()
    print(f"active fit fields: {plan['active_fit_fields']}", flush=True)
    cache = _build_cache(tm, layout, speed, altitude, track, gps_track, plan)
    print(f"cache build: {cache.build_ms:.1f} ms, mem {cache.memory_bytes/(1024*1024):.3f} MiB",
          flush=True)
    print(f"cache stats: {cache.stats()}", flush=True)

    frames = 1131
    boundary = [0, 1, 30, 300, 600, 900, 1129, 1130]
    total_mismatches = 0
    first = None
    max_diff = 0.0
    fields_compared = 0
    mismatch_frames = 0
    for f in range(frames):
        rec = _reference_kwargs(tm, layout, speed, altitude, track, gps_track, plan, f)
        pre = cache.lookup(f)
        fields_compared += len(rec)
        m, mx = _diff(rec, pre)
        if m:
            mismatch_frames += 1
            total_mismatches += len(m)
            if first is None:
                first = (f, m[0])
        max_diff = max(max_diff, mx)

    print(f"\nVALUE EXACTNESS (1131 frames):", flush=True)
    print(f"  frames compared: {frames}", flush=True)
    print(f"  fields compared: {fields_compared}", flush=True)
    print(f"  mismatch frames: {mismatch_frames}", flush=True)
    print(f"  total mismatches: {total_mismatches}", flush=True)
    print(f"  first mismatch: {first}", flush=True)
    print(f"  max numerical difference: {max_diff}", flush=True)

    # boundary/none frames detailed
    print(f"\nBOUNDARY FRAMES (all fields equal):", flush=True)
    ok = True
    for f in boundary:
        if f >= frames:
            continue
        rec = _reference_kwargs(tm, layout, speed, altitude, track, gps_track, plan, f)
        pre = cache.lookup(f)
        m, mx = _diff(rec, pre)
        print(f"  frame {f}: equal={not m} (mismatches={len(m)})", flush=True)
        if m:
            ok = False
    print(f"  boundary OK: {ok}", flush=True)

    # NONE handling: standard fields should be None in this layout
    f0 = cache.lookup(0)
    print(f"\nNONE checks: power={f0['power_value']} atemp={f0['atemp_value']} "
          f"hr={f0['hr_value']} cad={f0['cad_value']} battery={f0['battery_value']}",
          flush=True)

    # ── alternate layout: fractional_cadence ─────────────────────────────
    print("\n=== ALTERNATE LAYOUT (fractional_cadence) ===", flush=True)
    tm2, layout2, speed2, alt2, track2, gps2, plan2 = _setup(
        extra_fit="fit_fractional_cadence_text")
    print(f"active fit fields: {plan2['active_fit_fields']}", flush=True)
    cache2 = _build_cache(tm2, layout2, speed2, alt2, track2, gps2, plan2)
    mism2 = 0
    for f in (0, 30, 300, 1130):
        rec = _reference_kwargs(tm2, layout2, speed2, alt2, track2, gps2, plan2, f)
        pre = cache2.lookup(f)
        m, _ = _diff(rec, pre)
        if m:
            mism2 += len(m)
            print(f"  frame {f}: MISMATCH {m[:2]}", flush=True)
    print(f"  alternate layout mismatches: {mism2}", flush=True)
    frac = cache2.lookup(30).get("extra_indicators", {}).get("fit_fractional_cadence_text")
    print(f"  fit_fractional_cadence_text present in cache: {frac is not None}", flush=True)

    print("\n=== RESULT ===", flush=True)
    if total_mismatches == 0 and mism2 == 0 and ok:
        print("EXACTNESS GATE: PASS (mismatches=0, 1131 frames)", flush=True)
        return 0
    print("EXACTNESS GATE: FAIL", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
