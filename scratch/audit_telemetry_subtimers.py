"""Audit Telemetry/frame_data subtimers and measure per-field costs."""
import json
import time
import sys
from pathlib import Path
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache

def audit_telemetry():
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    json_path = root / "Video" / "GX030120.json"
    records = ensure_records_list(load_json_with_fallback(json_path))
    tm = TelemetryDataManager(
        extract_speed_samples, extract_altitude_samples, extract_track_samples,
        extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
        smooth_speed_samples, interpolate_value
    )
    tm.load_gpmf_records(records)
    tm.load_fit(fit_path)
    tm.start_dt_utc = tm.speed_samples[0][0]

    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    
    speed_samples = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
    alt_samples = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
    track_samples = tm.track_samples
    iso_samples = tm.iso_samples
    exposure_samples = tm.exposure_samples
    temperature_samples = tm.temperature_samples
    fit_data = tm.fit_data
    gps_track = tm.get_gps_track_for_source("fit")
    base_dt = tm.start_dt_utc
    total_frames = 900
    target_fps = 29.97002997

    # Measure build of precomputed cache
    t0 = time.perf_counter()
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=base_dt,
        tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temperature_samples,
        fit_data=fit_data,
        gps_track=gps_track,
        total_frames=total_frames,
        target_fps=target_fps,
    )
    cache_build_ms = (time.perf_counter() - t0) * 1000.0
    print(f"PRECOMPUTED cache build: {cache_build_ms:.2f} ms for {cache.frames} frames ({cache_build_ms/cache.frames:.3f} ms/frame)")

    # Measure lookup in precomputed cache
    lookup_times = []
    for f in range(total_frames):
        t0 = time.perf_counter()
        d = cache.lookup(f)
        lookup_times.append((time.perf_counter() - t0) * 1000.0)
    print(f"PRECOMPUTED lookup: median={np.median(lookup_times)*1000.0:.2f} µs, p95={np.percentile(lookup_times, 95)*1000.0:.2f} µs")

    # Now measure LIVE prepare_overlay_frame_data breakdown
    live_times = []
    breakdown = {
        "target_dt": [],
        "standard_gpmf_interp": [],
        "fit_fields_interp": [],
        "chart_payload": [],
        "dict_assembly": [],
    }

    # Extract field plan
    from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts
    from src.fit_resolve import build_fit_field_plan, resolve_fit_field_value

    fit_field_plan = build_fit_field_plan(layout, fit_data)
    print(f"FIT field plan items: {len(fit_field_plan)}")
    for k, info in fit_field_plan.items():
        print(f"  FIT plan: indicator '{k}' -> source={info.get('source')}, field={info.get('field_name')}, sample_count={len(info.get('samples', []))}")

    # Sub-timing breakdown run across 300 frames
    for f in range(300):
        t_start = time.perf_counter()
        
        # Subtimer 1: target_dt
        t0 = time.perf_counter()
        pts_s = f / target_fps
        curr_dt = base_dt + (speed_samples[-1][0] - speed_samples[0][0]) * (pts_s / 180.0)
        t_dt = (time.perf_counter() - t0) * 1000.0
        breakdown["target_dt"].append(t_dt)

        # Subtimer 2: standard gpmf interp
        t0 = time.perf_counter()
        sp_val = interpolate_value(speed_samples, curr_dt)
        alt_val = interpolate_value(alt_samples, curr_dt)
        trk_val = interpolate_value(track_samples, curr_dt)
        iso_val = interpolate_value(iso_samples, curr_dt)
        exp_val = interpolate_value(exposure_samples, curr_dt)
        tmp_val = interpolate_value(temperature_samples, curr_dt)
        t_gpmf = (time.perf_counter() - t0) * 1000.0
        breakdown["standard_gpmf_interp"].append(t_gpmf)

        # Subtimer 3: fit fields interp
        t0 = time.perf_counter()
        fit_vals = {}
        for ind_key, plan_info in fit_field_plan.items():
            s_list = plan_info.get("samples")
            if s_list:
                fit_vals[ind_key] = interpolate_value(s_list, curr_dt)
        t_fit = (time.perf_counter() - t0) * 1000.0
        breakdown["fit_fields_interp"].append(t_fit)

        # Subtimer 4: full prepare_overlay_frame_data call
        t0 = time.perf_counter()
        frame_dict = prepare_overlay_frame_data(
            layout=layout,
            target_dt=curr_dt,
            start_dt_utc=base_dt,
            tz_offset_hours=0.0,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temperature_samples,
            total_frames=total_frames,
            current_index=f,
            fit_data=fit_data,
            gps_track=gps_track,
            fit_field_plan=fit_field_plan,
        )
        t_full = (time.perf_counter() - t0) * 1000.0
        live_times.append(t_full)

    print("\n=== LIVE TELEMETRY / FRAME_DATA BREAKDOWN ===")
    print(f"Total prepare_overlay_frame_data: median = {np.median(live_times):.3f} ms, p95 = {np.percentile(live_times, 95):.3f} ms")
    for subk, times in breakdown.items():
        if times:
            print(f"  {subk:25s}: median = {np.median(times):.3f} ms, p95 = {np.percentile(times, 95):.3f} ms")

if __name__ == "__main__":
    audit_telemetry()
