import sys, os, time, json, math
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
import psutil
from PIL import Image
from datetime import datetime, timedelta
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor, interpolate_speed, interpolate_distance, interpolate_altitude,
    interpolate_iso, interpolate_exposure, interpolate_temperature
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.time_block import render_time_block
from src.indicators.dispatcher import render_value_indicator
from src.indicators.bar import _render_bar_indicator
from src.indicators.rotated_paste import rotated_paste
from src.ffmpeg.command_builder import get_layout_hud_regions
from src.ffmpeg.shared_memory import SharedFramePool, render_frame_shm_job, _init_worker_with_shm, WORKER_CACHE
from concurrent.futures import ProcessPoolExecutor, as_completed

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
n_frames = 1132
target_fps = 29.97

def profile_worker_detailed(layout, field_samples, fit_data, hud_regions, n_test_frames=1132):
    canvas_w = 1920
    canvas_h = 1080
    font_path = ""
    start_dt_utc = field_samples.get("start_dt_utc")
    speed_samples = field_samples.get("speed_samples", [])
    track_samples = field_samples.get("track_samples", [])
    alt_samples = field_samples.get("alt_samples", [])
    iso_samples = field_samples.get("iso_samples", [])
    exposure_samples = field_samples.get("exposure_samples", [])
    temp_samples = field_samples.get("temp_samples", [])
    gps_track = fit_data.get("track") if fit_data else None

    chart_data = None
    if fit_data:
        chart_data = {
            "hr": fit_data.get("heart_rate", []),
            "cadence": fit_data.get("cadence", []),
            "speed": fit_data.get("speed", []),
            "alt": fit_data.get("alt", []),
        }

    atlas_w = max(r[2] + r[4] for r in hud_regions)
    atlas_h = max(r[3] + r[5] for r in hud_regions)

    shm_buf = bytearray(atlas_w * atlas_h * 4)
    shm_arr = np.frombuffer(shm_buf, dtype=np.uint8).reshape((atlas_h, atlas_w, 4))

    records = []
    indicator_records = {}

    for idx in range(n_test_frames):
        target_dt = start_dt_utc + timedelta(seconds=idx / target_fps) if start_dt_utc else None
        t_job_start = time.perf_counter_ns()

        # PHASE A: Telemetry
        t_tele_start = time.perf_counter_ns()
        t_dt0 = time.perf_counter_ns()
        if target_dt:
            local_dt = target_dt
            date_text = local_dt.strftime("%Y-%m-%d")
            time_text = local_dt.strftime("%H:%M:%S")
        else:
            date_text, time_text = "", ""
        t_dt1 = time.perf_counter_ns()
        date_time_ns = t_dt1 - t_dt0

        t_lookup0 = time.perf_counter_ns()
        data = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target_dt,
            tz_offset_hours=0.0,
            start_dt_utc=start_dt_utc,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temp_samples,
            fit_data=fit_data,
            gps_track=gps_track,
            total_frames=n_test_frames,
            current_index=idx,
            chart_data=chart_data,
        )
        t_lookup1 = time.perf_counter_ns()
        telemetry_lookup_ns = t_lookup1 - t_lookup0
        t_tele_end = time.perf_counter_ns()
        total_telemetry_ns = t_tele_end - t_tele_start

        # PHASE B: Compose & Per-indicator
        t_compose_start = time.perf_counter_ns()
        ind_breakdown = {}
        
        t_c0 = time.perf_counter_ns()
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        t_c1 = time.perf_counter_ns()
        canvas_init_ns = t_c1 - t_c0

        # time_block
        if "time_block" in layout.get("indicators", {}):
            t_i0 = time.perf_counter_ns()
            tb, tbx, tby = render_time_block(canvas_w, canvas_h, layout, font_path, data["date_text"], data["time_text"])
            t_i1 = time.perf_counter_ns()
            if tb:
                cx = tbx + tb.width // 2
                cy = tby + tb.height // 2
                rotated_paste(img, tb, cx, cy, 0, cache_key="time_block")
            t_i2 = time.perf_counter_ns()
            ind_breakdown["time_block"] = {
                "render_ns": t_i1 - t_i0,
                "rotate_ns": 0,
                "composite_ns": t_i2 - t_i1,
                "total_ns": t_i2 - t_i0,
                "form": "text"
            }

        # other indicators
        for k, cfg in layout.get("indicators", {}).items():
            if k == "time_block" or not cfg.get("enabled", True):
                continue
            t_i0 = time.perf_counter_ns()
            w_img, rx, ry = render_value_indicator(
                canvas_w, canvas_h, cfg, k, font_path,
                data["speed_value"], data["distance_m"], data["max_distance_m"],
                data["alt_value"], data["min_alt"], data["max_alt"],
                data["iso_value"], data["exposure_value"], data["temp_value"],
                indicator_values=data.get("indicator_values"),
                max_speed_kmh=data.get("max_speed_kmh"),
                power_value=data.get("power_value"),
                atemp_value=data.get("atemp_value"),
                hr_value=data.get("hr_value"),
                cad_value=data.get("cad_value"),
                battery_value=data.get("battery_value"),
                chart_data=data.get("chart_data"),
                current_position=data.get("current_position"),
                extra_indicators=data.get("extra_indicators"),
                gps_track=data.get("gps_track"),
                target_dt=data.get("target_dt"),
                start_dt_utc=data.get("start_dt_utc"),
                elapsed_seconds=data.get("elapsed_seconds", 0.0),
                avg_speed_kmh=data.get("avg_speed_kmh", 0.0),
            )
            t_i1 = time.perf_counter_ns()
            rot = cfg.get("rotation", 0)
            if w_img:
                cx = rx + w_img.width // 2
                cy = ry + w_img.height // 2
                t_rot0 = time.perf_counter_ns()
                rotated_paste(img, w_img, cx, cy, rot, cache_key=k)
                t_rot1 = time.perf_counter_ns()
                rot_ns = (t_rot1 - t_rot0) if rot != 0 else 0
                comp_ns = (t_rot1 - t_rot0)
            else:
                rot_ns, comp_ns = 0, 0
                t_rot1 = t_i1

            ind_breakdown[k] = {
                "render_ns": t_i1 - t_i0,
                "rotate_ns": rot_ns,
                "composite_ns": comp_ns,
                "total_ns": t_rot1 - t_i0,
                "form": cfg.get("form", "text")
            }

        t_compose_end = time.perf_counter_ns()
        total_compose_ns = t_compose_end - t_compose_start

        # PHASE C & D: Atlas Crop & Pack
        t_atlas_start = time.perf_counter_ns()
        t_crop0 = time.perf_counter_ns()
        crops = []
        crop_per_region_ns = []
        for r in hud_regions:
            t_cr0 = time.perf_counter_ns()
            dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
            r_crop = img.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
            t_cr1 = time.perf_counter_ns()
            crop_per_region_ns.append(t_cr1 - t_cr0)
            crops.append((r_crop, atlas_x, atlas_y))
        t_crop1 = time.perf_counter_ns()
        total_crop_ns = t_crop1 - t_crop0

        t_pack0 = time.perf_counter_ns()
        atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
        t_alloc1 = time.perf_counter_ns()
        atlas_alloc_ns = t_alloc1 - t_pack0

        paste_per_region_ns = []
        for r_crop, ax, ay in crops:
            t_p0 = time.perf_counter_ns()
            atlas_img.paste(r_crop, (ax, ay))
            t_p1 = time.perf_counter_ns()
            paste_per_region_ns.append(t_p1 - t_p0)
        t_pack1 = time.perf_counter_ns()
        total_pack_ns = t_pack1 - t_pack0
        t_atlas_end = time.perf_counter_ns()
        total_atlas_ns = t_atlas_end - t_atlas_start

        # PHASE E & F: PIL -> NumPy & SHM Copy
        t_shm_start = time.perf_counter_ns()
        t_np0 = time.perf_counter_ns()
        img_arr = np.asarray(atlas_img)
        t_np1 = time.perf_counter_ns()
        numpy_conv_ns = t_np1 - t_np0

        t_cp0 = time.perf_counter_ns()
        np.copyto(shm_arr, img_arr)
        t_cp1 = time.perf_counter_ns()
        shm_copy_ns = t_cp1 - t_cp0
        t_shm_end = time.perf_counter_ns()
        total_shm_ns = t_shm_end - t_shm_start

        t_job_end = time.perf_counter_ns()
        total_job_ns = t_job_end - t_job_start

        record = {
            "index": idx,
            "total_job_ms": total_job_ns / 1e6,
            "telemetry_ms": total_telemetry_ns / 1e6,
            "date_time_ms": date_time_ns / 1e6,
            "telemetry_lookup_ms": telemetry_lookup_ns / 1e6,
            "compose_ms": total_compose_ns / 1e6,
            "canvas_init_ms": canvas_init_ns / 1e6,
            "atlas_total_ms": total_atlas_ns / 1e6,
            "atlas_crop_ms": total_crop_ns / 1e6,
            "atlas_crop_regions_ms": [c / 1e6 for c in crop_per_region_ns],
            "atlas_alloc_ms": atlas_alloc_ns / 1e6,
            "atlas_pack_ms": total_pack_ns / 1e6,
            "atlas_paste_regions_ms": [p / 1e6 for p in paste_per_region_ns],
            "shm_total_ms": total_shm_ns / 1e6,
            "numpy_conv_ms": numpy_conv_ns / 1e6,
            "shm_copy_ms": shm_copy_ns / 1e6,
            "unaccounted_ms": (total_job_ns - (total_telemetry_ns + total_compose_ns + total_atlas_ns + total_shm_ns)) / 1e6,
        }
        records.append(record)
        if ind_breakdown:
            for k, val in ind_breakdown.items():
                if k not in indicator_records:
                    indicator_records[k] = []
                indicator_records[k].append(val)

    return records, indicator_records

def test_rotation_costs(layout, font_path=""):
    """Benchmark rotation and bar styles specifically."""
    print("\n--- TEST ROTATION & BAR STYLES (0°, 90°, 180°, 270°) ---")
    results = {}
    canvas_w, canvas_h = 1920, 1080
    test_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # Test bar ruler vs segments at 0 vs 90 deg
    for style in ("ruler", "segments"):
        for rot in (0, 90, 180, 270):
            cfg = {
                "enabled": True, "form": "bar", "bar_style": style,
                "size": 0.2, "rotation": rot, "min_val": 0, "max_val": 100,
                "label": "Alt", "unit": "m", "color": "#00ff00"
            }
            render_times = []
            rotate_paste_times = []
            for _ in range(100):
                t0 = time.perf_counter_ns()
                w_img, rx, ry = _render_bar_indicator(canvas_w, canvas_h, cfg, "alt_visual", font_path, 50.0, 0.0, 100.0)
                t1 = time.perf_counter_ns()
                cx = rx + w_img.width // 2
                cy = ry + w_img.height // 2
                rotated_paste(test_img, w_img, cx, cy, rot, cache_key=f"alt_test_{style}_{rot}")
                t2 = time.perf_counter_ns()
                render_times.append((t1 - t0) / 1e6)
                rotate_paste_times.append((t2 - t1) / 1e6)

            med_r = float(np.median(render_times[10:]))
            med_p = float(np.median(rotate_paste_times[10:]))
            results[f"bar_{style}_rot_{rot}"] = {
                "render_ms": med_r,
                "paste_rotate_ms": med_p,
                "total_ms": med_r + med_p
            }
            print(f"Bar {style:8s} rot={rot:3d}°: render={med_r:.3f} ms | rotate_paste={med_p:.3f} ms | total={med_r+med_p:.3f} ms")

    return results

def run_multiprocessing_profile(layout, field_samples, fit_data, hud_regions):
    """Run full 4-worker ProcessPoolExecutor and measure scheduling/IPC."""
    print("\n--- MULTIPROCESSING / SCHEDULING PROFILE (4 WORKERS, 8 SLOTS) ---")
    atlas_w = max(r[2] + r[4] for r in hud_regions)
    atlas_h = max(r[3] + r[5] for r in hud_regions)
    frame_size = atlas_w * atlas_h * 4

    pool = SharedFramePool(8, frame_size)
    init_args = (
        layout, "", 1920, 1080,
        field_samples.get("speed_samples"), field_samples.get("track_samples"), field_samples.get("alt_samples"),
        target_fps, 1, 1132,
        field_samples.get("iso_samples"), field_samples.get("exposure_samples"), field_samples.get("temp_samples"),
        fit_data, fit_data.get("track") if fit_data else None,
        0, False, hud_regions, None
    )

    t_start = time.perf_counter()
    submitted = 0
    completed = 0
    pending = set()
    wait_times = []
    in_flight_samples = []

    with ProcessPoolExecutor(max_workers=4, initializer=_init_worker_with_shm, initargs=(pool.names, frame_size, *init_args)) as ex:
        for _ in range(min(8, 1132)):
            slot = pool.acquire_free_slot(timeout=5.0)
            pending.add(ex.submit(render_frame_shm_job, (submitted, slot)))
            submitted += 1

        while completed < 1132:
            in_flight_samples.append(len(pending))
            t_w0 = time.perf_counter()
            done, pending = as_completed(pending, timeout=10.0), set()
            for fut in done:
                idx, slot = fut.result()
                pool.release_slot_to_writer(slot)
                # simulate pipe read / consumption
                read_slot = pool.acquire_ready_slot(timeout=1.0)
                pool.release_slot_to_free(read_slot)
                completed += 1
                if submitted < 1132:
                    new_slot = pool.acquire_free_slot(timeout=5.0)
                    pending.add(ex.submit(render_frame_shm_job, (submitted, new_slot)))
                    submitted += 1
            t_w1 = time.perf_counter()
            wait_times.append((t_w1 - t_w0) * 1000.0)

    t_end = time.perf_counter()
    total_sec = t_end - t_start
    total_fps = 1132 / total_sec

    pool.cleanup()
    res = {
        "total_elapsed_s": total_sec,
        "total_fps": total_fps,
        "avg_wait_ms": float(np.mean(wait_times)),
        "p95_wait_ms": float(np.percentile(wait_times, 95)),
        "avg_in_flight": float(np.mean(in_flight_samples)),
    }
    print(f"ProcessPoolExecutor: {1132} frames in {total_sec:.3f} s -> {total_fps:.1f} FPS (avg in-flight: {res['avg_in_flight']:.1f}, wait avg: {res['avg_wait_ms']:.2f} ms)")
    return res

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

    # 1. Standard def_layout.json
    prod_layout = normalize_layout("def_layout.json", 1920, 1080)
    aw, ah, hud_regs = get_layout_hud_regions(prod_layout, 1920, 1080, max_regions=3)

    print("=" * 70)
    print("ETAP 5A: CPU HUD PRODUCER PROFILING (1132 FRAMES)")
    print("=" * 70)

    # 1. Measure instrumentation overhead (profiling ON vs OFF)
    print("\n1. Testing instrumentation overhead...")
    t0 = time.perf_counter()
    recs_on, ind_on = profile_worker_detailed(prod_layout, field_samples, fit_data, hud_regs, n_test_frames=1132)
    t1 = time.perf_counter()
    time_on = t1 - t0

    t2 = time.perf_counter()
    recs_off, ind_off = profile_worker_detailed(prod_layout, field_samples, fit_data, hud_regs, n_test_frames=1132)
    t3 = time.perf_counter()
    time_off = t3 - t2

    overhead_pct = ((time_on - time_off) / time_off) * 100.0
    print(f"Instrumentation test: ON={time_on:.3f} s, OFF={time_off:.3f} s -> Overhead: {overhead_pct:+.2f}%")

    # 2. Rotation & bar styles test
    rot_results = test_rotation_costs(prod_layout)

    # 3. Multiprocessing scheduling test
    mp_results = run_multiprocessing_profile(prod_layout, field_samples, fit_data, hud_regs)

    # 4. Statistical aggregation (Cold vs Steady-State)
    cold_recs = recs_on[:30]
    steady_recs = recs_on[30:]

    def agg_phase(key, recs):
        vals = [r[key] for r in recs]
        return {
            "avg": float(np.mean(vals)),
            "median": float(np.median(vals)),
            "p95": float(np.percentile(vals, 95)),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
        }

    job_steady = agg_phase("total_job_ms", steady_recs)
    tele_steady = agg_phase("telemetry_ms", steady_recs)
    comp_steady = agg_phase("compose_ms", steady_recs)
    atlas_crop_steady = agg_phase("atlas_crop_ms", steady_recs)
    atlas_pack_steady = agg_phase("atlas_pack_ms", steady_recs)
    atlas_total_steady = agg_phase("atlas_total_ms", steady_recs)
    np_conv_steady = agg_phase("numpy_conv_ms", steady_recs)
    shm_copy_steady = agg_phase("shm_copy_ms", steady_recs)
    unaccounted_steady = agg_phase("unaccounted_ms", steady_recs)

    # Per-indicator statistics
    ind_stats = {}
    for ind_name, vals in ind_on.items():
        # skip first 30
        s_vals = vals[30:] if len(vals) > 30 else vals
        rend_list = [v["render_ns"] / 1e6 for v in s_vals]
        rot_list = [v["rotate_ns"] / 1e6 for v in s_vals]
        comp_list = [v["composite_ns"] / 1e6 for v in s_vals]
        tot_list = [v["total_ns"] / 1e6 for v in s_vals]
        ind_stats[ind_name] = {
            "form": s_vals[0].get("form", "text"),
            "render_avg_ms": float(np.mean(rend_list)),
            "rotate_avg_ms": float(np.mean(rot_list)),
            "composite_avg_ms": float(np.mean(comp_list)),
            "total_avg_ms": float(np.mean(tot_list)),
            "total_p95_ms": float(np.percentile(tot_list, 95)),
        }

    out_data = {
        "job_steady": job_steady,
        "telemetry_steady": tele_steady,
        "compose_steady": comp_steady,
        "atlas_crop_steady": atlas_crop_steady,
        "atlas_pack_steady": atlas_pack_steady,
        "atlas_total_steady": atlas_total_steady,
        "numpy_conv_steady": np_conv_steady,
        "shm_copy_steady": shm_copy_steady,
        "unaccounted_steady": unaccounted_steady,
        "indicator_stats": ind_stats,
        "rotation_stats": rot_results,
        "mp_stats": mp_results,
        "overhead_pct": overhead_pct,
        "cold_job_avg_ms": float(np.mean([r["total_job_ms"] for r in cold_recs])),
    }

    with open("scratch/etap5a_profile_results.json", "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)

    print("\n" + "=" * 70)
    print("ETAP 5A PROFILING COMPLETE! Results saved to scratch/etap5a_profile_results.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
