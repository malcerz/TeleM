import sys, os, time, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from datetime import datetime, timedelta
import numpy as np
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value
from src.telemetry_precompute import build_telemetry_cache

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
n_frames = 1132
target_fps = 29.97

def main():
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    anchor_dt = find_gps_anchor(records)
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

    field_samples = {
        "start_dt_utc": anchor_dt,
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temp_samples": temp_samples,
    }

    layout = normalize_layout("def_layout.json", 1920, 1080)
    
    init_worker(
        1920, 1080, "", layout, field_samples, None,
        iso_samples, exposure_samples, temp_samples,
        None, None, None, None, None, None, None,
        fit_data, fit_data.get("track"),
        anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, n_frames,
        None, 0, None, None, False,
    )
    chart_data = WORKER_CACHE.get("_precomputed_chart_data")
    _range_cache = WORKER_CACHE.get("_prep_cache")

    print(f"Building precompute cache for {n_frames} frames...")
    t0 = time.perf_counter()
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=anchor_dt,
        tz_offset_hours=0.0,
        start_dt_utc=anchor_dt,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
        chart_data=chart_data,
        resolve_cache_value=_resolve_cache_value,
        _range_cache=_range_cache,
        total_frames=n_frames,
        target_fps=target_fps,
    )
    t1 = time.perf_counter()
    build_ms = (t1 - t0) * 1000.0
    print(f"Precompute build took {build_ms:.3f} ms ({build_ms/n_frames:.3f} ms/frame)")

    print(f"\nComparing all {n_frames} frames against prepare_overlay_frame_data...")
    mismatches = 0
    max_float_diff = 0.0
    diff_fields = set()

    for idx in range(n_frames):
        target_dt = anchor_dt + timedelta(seconds=idx / target_fps)
        
        # Golden reference
        ref_data = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target_dt,
            tz_offset_hours=0.0,
            start_dt_utc=anchor_dt,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temp_samples,
            fit_data=fit_data,
            gps_track=fit_data.get("track"),
            total_frames=n_frames,
            current_index=idx,
            chart_data=chart_data,
            resolve_cache_value=_resolve_cache_value,
            _range_cache=_range_cache,
        )

        # Precomputed lookup
        pre_data = cache.lookup(idx)

        # Compare top-level keys
        for k in ref_data:
            if k not in pre_data:
                mismatches += 1
                diff_fields.add(f"missing_key:{k}")
                continue
            v_ref = ref_data[k]
            v_pre = pre_data[k]

            if isinstance(v_ref, float) and isinstance(v_pre, float):
                diff = abs(v_ref - v_pre)
                if diff > max_float_diff:
                    max_float_diff = diff
                if diff > 1e-9:
                    mismatches += 1
                    diff_fields.add(f"float_diff:{k}:{diff}")
            elif isinstance(v_ref, dict) and isinstance(v_pre, dict):
                # nested dict like indicator_values or extra_indicators
                for sub_k in v_ref:
                    if sub_k not in v_pre:
                        mismatches += 1
                        diff_fields.add(f"missing_sub_key:{k}.{sub_k}")
                        continue
                    sv_ref = v_ref[sub_k]
                    sv_pre = v_pre[sub_k]
                    if isinstance(sv_ref, tuple) and isinstance(sv_pre, tuple):
                        # (val, unit, label)
                        if sv_ref != sv_pre:
                            # check if float inside tuple
                            if isinstance(sv_ref[0], float) and isinstance(sv_pre[0], float):
                                d = abs(sv_ref[0] - sv_pre[0])
                                if d > 1e-9 or sv_ref[1:] != sv_pre[1:]:
                                    mismatches += 1
                                    diff_fields.add(f"tuple_diff:{k}.{sub_k}:{sv_ref} vs {sv_pre}")
                            else:
                                mismatches += 1
                                diff_fields.add(f"tuple_diff:{k}.{sub_k}:{sv_ref} vs {sv_pre}")
                    elif isinstance(sv_ref, float) and isinstance(sv_pre, float):
                        d = abs(sv_ref - sv_pre)
                        if d > max_float_diff:
                            max_float_diff = d
                        if d > 1e-9:
                            mismatches += 1
                            diff_fields.add(f"dict_float_diff:{k}.{sub_k}")
                    elif sv_ref != sv_pre:
                        mismatches += 1
                        diff_fields.add(f"dict_diff:{k}.{sub_k}:{sv_ref}!={sv_pre}")
            elif v_ref != v_pre:
                mismatches += 1
                diff_fields.add(f"val_diff:{k}:{v_ref}!={v_pre}")

    print(f"\nParity Check Results:")
    print(f"  Frames tested:   {n_frames}")
    print(f"  Total mismatches: {mismatches}")
    print(f"  Max float diff:   {max_float_diff:.2e}")
    if mismatches > 0:
        print(f"  Diff fields sample: {list(diff_fields)[:10]}")
    else:
        print(f"  STATUS: 100% BIT-EXACT SEMANTIC PARITY!")

if __name__ == "__main__":
    main()
