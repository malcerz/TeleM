import sys, os, time, json, math
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

os.environ["AMD_OVERLAY_PROFILE"] = "1"

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
    find_gps_anchor
)
from src.indicators.profiling import get_overlay_profiler
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.bar import _render_bar_indicator
from src.indicators.dispatcher import render_value_indicator
from src.indicators.rotated_paste import rotated_paste
from src.ffmpeg.command_builder import get_layout_hud_regions
from src.ffmpeg.shared_memory import SharedFramePool, render_frame_shm_job, _init_worker_with_shm
from concurrent.futures import ProcessPoolExecutor, as_completed

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
n_frames = 1132
target_fps = 29.97

from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value

def profile_producer_frames(layout, field_samples, fit_data, hud_regions, n_test_frames=1132):
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

    # Use production init_worker to initialize WORKER_CACHE
    init_worker(
        canvas_w, canvas_h, font_path, layout, field_samples, None,
        iso_samples, exposure_samples, temp_samples,
        None, None, None, None, None, None, None,
        fit_data, gps_track,
        start_dt_utc, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, n_test_frames,
        None, 0, None, hud_regions, False,
    )
    chart_data = WORKER_CACHE.get("_precomputed_chart_data")

    atlas_w = max(r[2] + r[4] for r in hud_regions)
    atlas_h = max(r[3] + r[5] for r in hud_regions)

    shm_buf = bytearray(atlas_w * atlas_h * 4)
    shm_arr = np.frombuffer(shm_buf, dtype=np.uint8).reshape((atlas_h, atlas_w, 4))

    profiler = get_overlay_profiler()
    profiler.install_pillow_hooks()

    job_timings = []

    for idx in range(n_test_frames):
        target_dt = start_dt_utc + timedelta(seconds=idx / target_fps) if start_dt_utc else None
        
        # Start frame profiling in profiler
        profiler.start_frame(idx, canvas_w, canvas_h)
        
        t_job0 = time.perf_counter_ns()

        # Phase A: Telemetry
        t_tele0 = time.perf_counter_ns()
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
            resolve_cache_value=_resolve_cache_value,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
        )
        t_tele1 = time.perf_counter_ns()

        # Phase B: Compose
        t_comp0 = time.perf_counter_ns()
        img = compose_overlay(
            canvas_w, canvas_h, layout, font_path,
            data["date_text"], data["time_text"],
            data["speed_value"], data["distance_m"], data["max_distance_m"],
            data["alt_value"], data["min_alt"], data["max_alt"],
            data["iso_value"], data["exposure_value"], data["temp_value"],
            indicator_values=data["indicator_values"],
            max_speed_kmh=data["max_speed_kmh"],
            power_value=data["power_value"],
            atemp_value=data["atemp_value"],
            hr_value=data["hr_value"],
            cad_value=data["cad_value"],
            battery_value=data["battery_value"],
            chart_data=data["chart_data"],
            current_position=data["current_position"],
            extra_indicators=data["extra_indicators"],
            gps_track=data["gps_track"],
            target_dt=data["target_dt"],
            start_dt_utc=data["start_dt_utc"],
            elapsed_seconds=data["elapsed_seconds"],
            avg_speed_kmh=data["avg_speed_kmh"],
        )
        t_comp1 = time.perf_counter_ns()

        # Phase C: Atlas Crop
        t_crop0 = time.perf_counter_ns()
        crops = []
        crop_regions_ns = []
        for r in hud_regions:
            t_cr0 = time.perf_counter_ns()
            dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
            r_crop = img.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
            t_cr1 = time.perf_counter_ns()
            crop_regions_ns.append(t_cr1 - t_cr0)
            crops.append((r_crop, atlas_x, atlas_y))
        t_crop1 = time.perf_counter_ns()

        # Phase D: Atlas Pack
        t_pack0 = time.perf_counter_ns()
        atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
        t_alloc1 = time.perf_counter_ns()
        paste_regions_ns = []
        for r_crop, ax, ay in crops:
            t_p0 = time.perf_counter_ns()
            atlas_img.paste(r_crop, (ax, ay))
            t_p1 = time.perf_counter_ns()
            paste_regions_ns.append(t_p1 - t_p0)
        t_pack1 = time.perf_counter_ns()

        # Phase E & F: PIL -> NumPy & SHM Copy
        t_shm0 = time.perf_counter_ns()
        t_np0 = time.perf_counter_ns()
        img_arr = np.asarray(atlas_img)
        t_np1 = time.perf_counter_ns()
        t_cp0 = time.perf_counter_ns()
        np.copyto(shm_arr, img_arr)
        t_cp1 = time.perf_counter_ns()
        t_shm1 = time.perf_counter_ns()

        t_job1 = time.perf_counter_ns()

        # Record top-level metrics in profiler frame
        total_job_ms = (t_job1 - t_job0) / 1e6
        telemetry_ms = (t_tele1 - t_tele0) / 1e6
        compose_ms = (t_comp1 - t_comp0) / 1e6
        atlas_crop_ms = (t_crop1 - t_crop0) / 1e6
        atlas_alloc_ms = (t_alloc1 - t_pack0) / 1e6
        atlas_pack_ms = (t_pack1 - t_pack0) / 1e6
        numpy_conv_ms = (t_np1 - t_np0) / 1e6
        shm_copy_ms = (t_cp1 - t_cp0) / 1e6
        atlas_total_ms = (t_pack1 - t_crop0) / 1e6
        shm_total_ms = (t_shm1 - t_shm0) / 1e6
        unaccounted_ms = total_job_ms - (telemetry_ms + compose_ms + atlas_total_ms + shm_total_ms)

        job_timings.append({
            "frame": idx,
            "total_job_ms": total_job_ms,
            "telemetry_ms": telemetry_ms,
            "compose_ms": compose_ms,
            "atlas_crop_ms": atlas_crop_ms,
            "atlas_alloc_ms": atlas_alloc_ms,
            "atlas_pack_ms": atlas_pack_ms,
            "atlas_total_ms": atlas_total_ms,
            "numpy_conv_ms": numpy_conv_ms,
            "shm_copy_ms": shm_copy_ms,
            "shm_total_ms": shm_total_ms,
            "unaccounted_ms": unaccounted_ms,
            "crop_regions_ms": [c / 1e6 for c in crop_regions_ns],
            "paste_regions_ms": [p / 1e6 for p in paste_regions_ns],
        })

        profiler.finish_frame()

    return job_timings, profiler.summary()

def test_rotation_matrix(prod_layout):
    print("\n--- ROTATION MATRIX (0°, 90°, 180°, 270°) FOR RULER & SEGMENTS ---")
    results = {}
    canvas_w, canvas_h = 1920, 1080
    test_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    for style in ("ruler", "segments"):
        for rot in (0, 90, 180, 270):
            cfg = {
                "enabled": True, "form": "bar", "bar_style": style,
                "size": 0.2, "rotation": rot, "min_val": 0, "max_val": 100,
                "label": "Alt", "unit": "m", "color": "#00ff00", "thickness": 2, "font_size": 20,
                "x": 10.0, "y": 80.0
            }
            r_times = []
            p_times = []
            for _ in range(100):
                t0 = time.perf_counter_ns()
                w_img, rx, ry, _ = render_value_indicator(
                    canvas_w, canvas_h, prod_layout, "", "alt_visual", 50.0, "m", "Alt", cfg_override=cfg
                )
                t1 = time.perf_counter_ns()
                if w_img:
                    cx = rx + w_img.width // 2
                    cy = ry + w_img.height // 2
                    rotated_paste(test_img, w_img, cx, cy, rot, cache_key=f"alt_{style}_{rot}")
                t2 = time.perf_counter_ns()
                r_times.append((t1 - t0) / 1e6)
                p_times.append((t2 - t1) / 1e6)

            med_r = float(np.median(r_times[10:]))
            med_p = float(np.median(p_times[10:]))
            results[f"bar_{style}_rot_{rot}"] = {
                "render_ms": med_r,
                "paste_ms": med_p,
                "total_ms": med_r + med_p
            }
            print(f"  Bar {style:8s} rot={rot:3d}°: render={med_r:.3f} ms | paste={med_p:.3f} ms | total={med_r+med_p:.3f} ms")

    return results

def test_multiprocessing_pool(layout, field_samples, fit_data, hud_regions):
    print("\n--- MULTIPROCESSING / SCHEDULING (4 WORKERS, 8 SLOTS, 1132 FRAMES) ---")
    atlas_w = max(r[2] + r[4] for r in hud_regions)
    atlas_h = max(r[3] + r[5] for r in hud_regions)
    frame_size = atlas_w * atlas_h * 4

    pool = SharedFramePool(8, frame_size)
    init_args = (
        1920, 1080, "", layout, field_samples, None,
        field_samples.get("iso_samples"), field_samples.get("exposure_samples"), field_samples.get("temp_samples"),
        None, None, None,
        None, None, None, None,
        fit_data,
        fit_data.get("track") if fit_data else None,
        field_samples.get("start_dt_utc"), 0.0,
        field_samples.get("speed_samples"), field_samples.get("track_samples"), field_samples.get("alt_samples"),
        target_fps, 1, 1132,
        None, 0, None, hud_regions,
        False,
    )

    t0 = time.perf_counter()
    submitted = 0
    completed = 0
    pending = set()
    wait_times = []
    in_flight_counts = []

    with ProcessPoolExecutor(max_workers=4, initializer=_init_worker_with_shm, initargs=(pool.shm_names(), frame_size, *init_args)) as ex:
        for _ in range(min(8, 1132)):
            slot = pool.acquire(timeout=5.0)
            pending.add(ex.submit(render_frame_shm_job, (submitted, slot)))
            submitted += 1

        while completed < 1132:
            in_flight_counts.append(len(pending))
            t_w0 = time.perf_counter()
            done, pending = as_completed(pending, timeout=10.0), set()
            for fut in done:
                idx, slot = fut.result()
                # simulate consumer reading the slot
                mv = pool.get_memview(slot)
                _ = len(mv) # simulated instant access
                pool.release(slot)
                completed += 1
                if submitted < 1132:
                    new_slot = pool.acquire(timeout=5.0)
                    pending.add(ex.submit(render_frame_shm_job, (submitted, new_slot)))
                    submitted += 1
            t_w1 = time.perf_counter()
            wait_times.append((t_w1 - t_w0) * 1000.0)

    t1 = time.perf_counter()
    elapsed = t1 - t0
    fps = 1132 / elapsed
    pool.close()

    res = {
        "elapsed_s": elapsed,
        "fps": fps,
        "avg_wait_ms": float(np.mean(wait_times)),
        "p95_wait_ms": float(np.percentile(wait_times, 95)),
        "avg_in_flight": float(np.mean(in_flight_counts)),
    }
    print(f"  Result: 1132 frames in {elapsed:.3f} s -> {fps:.1f} FPS (avg wait: {res['avg_wait_ms']:.2f} ms, in-flight: {res['avg_in_flight']:.1f})")
    return res

def test_profiling_overhead(layout, field_samples, fit_data, hud_regions):
    print("\n--- TESTING PROFILING OVERHEAD (OFF vs ON) ---")
    # 1. Profiling OFF
    os.environ["AMD_OVERLAY_PROFILE"] = "0"
    profiler = get_overlay_profiler()
    profiler.enabled = False

    t0 = time.perf_counter()
    profile_producer_frames(layout, field_samples, fit_data, hud_regions, n_test_frames=300)
    t1 = time.perf_counter()
    off_sec = t1 - t0

    # 2. Profiling ON
    os.environ["AMD_OVERLAY_PROFILE"] = "1"
    profiler.enabled = True

    t2 = time.perf_counter()
    profile_producer_frames(layout, field_samples, fit_data, hud_regions, n_test_frames=300)
    t3 = time.perf_counter()
    on_sec = t3 - t2

    overhead = ((on_sec - off_sec) / off_sec) * 100.0
    print(f"  Profiling OFF: {off_sec:.3f} s ({300/off_sec:.1f} FPS)")
    print(f"  Profiling ON:  {on_sec:.3f} s ({300/on_sec:.1f} FPS)")
    print(f"  Overhead:      {overhead:+.2f}%")
    return overhead

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

    prod_layout = normalize_layout("def_layout.json", 1920, 1080)
    aw, ah, hud_regs = get_layout_hud_regions(prod_layout, 1920, 1080, max_regions=3)

    print("=" * 70)
    print("ETAP 5A: IN-DEPTH CPU HUD PRODUCER PROFILING (1132 FRAMES)")
    print("=" * 70)

    # 1. Profiling overhead
    overhead_pct = test_profiling_overhead(prod_layout, field_samples, fit_data, hud_regs)

    # 2. Main profiling execution (1132 frames)
    print("\n--- RUNNING FULL 1132 FRAMES PROFILING ---")
    profiler = get_overlay_profiler()
    os.environ["AMD_OVERLAY_PROFILE"] = "1"
    profiler.enabled = True
    profiler._frames.clear()
    profiler._geometries.clear()
    timings, profiler_summary = profile_producer_frames(prod_layout, field_samples, fit_data, hud_regs, n_test_frames=1132)

    # 3. Rotation tests
    rot_stats = test_rotation_matrix(prod_layout)

    # 4. Multiprocessing scheduling test
    mp_stats = test_multiprocessing_pool(prod_layout, field_samples, fit_data, hud_regs)

    # 5. Process & aggregate statistics
    cold = timings[:30]
    steady = timings[30:]

    def stats_for(key, arr):
        v = [x[key] for x in arr]
        return {
            "avg": float(np.mean(v)),
            "median": float(np.median(v)),
            "p95": float(np.percentile(v, 95)),
            "min": float(np.min(v)),
            "max": float(np.max(v)),
        }

    steady_stats = {
        "total_job": stats_for("total_job_ms", steady),
        "telemetry": stats_for("telemetry_ms", steady),
        "compose": stats_for("compose_ms", steady),
        "atlas_crop": stats_for("atlas_crop_ms", steady),
        "atlas_alloc": stats_for("atlas_alloc_ms", steady),
        "atlas_pack": stats_for("atlas_pack_ms", steady),
        "atlas_total": stats_for("atlas_total_ms", steady),
        "numpy_conv": stats_for("numpy_conv_ms", steady),
        "shm_copy": stats_for("shm_copy_ms", steady),
        "shm_total": stats_for("shm_total_ms", steady),
        "unaccounted": stats_for("unaccounted_ms", steady),
    }

    cold_stats = {
        "total_job": stats_for("total_job_ms", cold),
        "telemetry": stats_for("telemetry_ms", cold),
        "compose": stats_for("compose_ms", cold),
        "atlas_total": stats_for("atlas_total_ms", cold),
        "shm_total": stats_for("shm_total_ms", cold),
    }

    # Extract per-indicator and per-pillow metrics from profiler_summary
    metrics = profiler_summary.get("metrics", {})
    indicators_breakdown = {}
    pillow_ops = {}

    for k, m in metrics.items():
        if k.startswith("indicator."):
            parts = k.split(".")
            # e.g. indicator.time_block.total or indicator.fit_cadence_text.render
            ind_name = parts[1]
            op_name = ".".join(parts[2:])
            if ind_name not in indicators_breakdown:
                indicators_breakdown[ind_name] = {}
            indicators_breakdown[ind_name][op_name] = {
                "avg_ms": m["avg_ms"],
                "median_ms": m["median_ms"],
                "p95_ms": m["p95_ms"],
            }
        elif k.startswith("pillow."):
            op = k.split(".", 1)[1]
            pillow_ops[op] = {
                "avg_ms": m["avg_ms"],
                "median_ms": m["median_ms"],
                "p95_ms": m["p95_ms"],
                "avg_calls": m["avg_calls_per_frame"],
                "avg_pixels": m["avg_pixels_per_frame"],
            }

    full_output = {
        "steady_stats": steady_stats,
        "cold_stats": cold_stats,
        "indicators_breakdown": indicators_breakdown,
        "pillow_ops": pillow_ops,
        "rotation_stats": rot_stats,
        "mp_stats": mp_stats,
        "overhead_pct": overhead_pct,
    }

    with open("scratch/etap5a_detailed_results.json", "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    print("\n" + "=" * 70)
    print("PROFILING RUN COMPLETED SUCCESSFULLY! Output saved to scratch/etap5a_detailed_results.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
