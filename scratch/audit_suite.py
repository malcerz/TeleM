import sys, os, time, math, statistics
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
from datetime import datetime, timezone, timedelta
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from PIL import Image, ImageDraw

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE
from src.ffmpeg.frame_renderer import render_overlay_frame
from src.indicators.compositor import compose_overlay, _get_reusable_canvas, render_preview
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.dispatcher import render_value_indicator
from src.indicators.time_block import render_time_block
from src.indicators.rotated_paste import rotated_paste
from src.ffmpeg.shared_memory import SharedFramePool, _init_worker_with_shm, render_frame_shm_job

def main():
    v_file = Path('Video/GX020079.mp4')
    fit_file = Path('Video/Morning_Ride.fit')

    print(f"[AUDIT] Extracting telemetry from {v_file}...")
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    anchor_dt = find_gps_anchor(records)
    print(f"[AUDIT] Anchor DT: {anchor_dt}")
    
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)
    layout = normalize_layout(None, 1920, 1080)
    total_frames = 1131
    target_fps = 29.97

    # ─────────────────────────────────────────────────────────────
    # PART 1: EXPORT VS PREVIEW RESOLUTION PROFILING
    # ─────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("PART 1: EXPORT (1080p HUD) vs PREVIEW (4K Full composite)")
    print("="*70)

    # 1.A: Preview frame rendering at 4K (3840x2160)
    preview_layout = normalize_layout(None, 3840, 2160)
    raw_4k_img = Image.new("RGBA", (3840, 2160), (30, 30, 30, 255))
    
    preview_times = []
    for i in range(10):
        t0 = time.perf_counter()
        pv = render_preview(
            raw_4k_img, preview_layout, "",
            "2026-08-05", "06:55:50",
            50.0, 1000.0, 5000.0, 200.0, 100.0, 300.0,
            100.0, 0.01, 25.0,
            indicator_values={}, max_speed_kmh=80.0,
            power_value=250.0, atemp_value=22.0, hr_value=145.0, cad_value=85.0, battery_value=90.0,
            chart_data={}, current_position=0.5, gps_track=fit_data.get("track"),
            target_dt=anchor_dt, start_dt_utc=anchor_dt,
            elapsed_seconds=1.0, avg_speed_kmh=45.0,
        )
        t1 = time.perf_counter()
        preview_times.append((t1 - t0) * 1000.0)
    
    print(f"4K Preview render_preview (CPU full composite): avg={statistics.mean(preview_times):.2f} ms | min={min(preview_times):.2f} ms | max={max(preview_times):.2f} ms")

    # 1.B: 1080p Export overlay frame rendering (compose_overlay + worker context)
    init_worker(
        1920, 1080, "", layout, {}, 0.0,
        iso_samples, exposure_samples, temp_samples,
        None, None, None,
        None, None, None, None,
        fit_data, fit_data.get("track"),
        anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, total_frames,
        cut_regions=[], effective_rotation=0,
        hud_bbox=None, hud_regions=None, hud_rotate_180=False,
    )

    export_frame_times = []
    for i in range(50):
        t0 = time.perf_counter()
        ov = render_overlay_frame(i, anchor_dt, 0.0, speed_samples, track_samples, alt_samples, target_fps)
        t1 = time.perf_counter()
        export_frame_times.append((t1 - t0) * 1000.0)

    print(f"1080p Export render_overlay_frame (single worker): avg={statistics.mean(export_frame_times):.2f} ms | p95={statistics.quantiles(export_frame_times, n=20)[18]:.2f} ms | min={min(export_frame_times):.2f} ms | max={max(export_frame_times):.2f} ms")

    # ─────────────────────────────────────────────────────────────
    # PART 2: DETAILED TIME BREAKDOWN OF 1080p OVERLAY COMPONENTS
    # ─────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("PART 2: DETAILED BREAKDOWN OF 1080p OVERLAY RENDERING")
    print("="*70)

    breakdown = {
        "telemetry_prep": [],
        "canvas_clear": [],
        "time_block_render": [],
        "time_block_paste": [],
        "indicators_render": {},
        "indicators_paste": {},
        "custom_text": [],
        "atlas_crop": [],
    }

    for ind in layout.get("indicators", {}):
        breakdown["indicators_render"][ind] = []
        breakdown["indicators_paste"][ind] = []

    for i in range(10, 60):
        sample_t = i / target_fps
        current_dt = anchor_dt + timedelta(seconds=sample_t)

        # 1. Telemetry prep
        t0 = time.perf_counter()
        data = prepare_overlay_frame_data(
            layout=layout,
            target_dt=current_dt,
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
            total_frames=total_frames,
            current_index=i,
            chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        )
        t1 = time.perf_counter()
        breakdown["telemetry_prep"].append((t1 - t0) * 1000.0)

        # 2. Canvas clear
        t0 = time.perf_counter()
        img, prev_bboxes, canvas_state = _get_reusable_canvas(1920, 1080, "below")
        if prev_bboxes:
            for bx, by, bw, bh in prev_bboxes.values():
                img.paste((0, 0, 0, 0), (max(0, bx-40), max(0, by-40), min(1920, bx+bw+40), min(1080, by+bh+40)))
            prev_bboxes.clear()
        t1 = time.perf_counter()
        breakdown["canvas_clear"].append((t1 - t0) * 1000.0)

        # 3. Time block
        if "time_block" in layout.get("indicators", {}):
            t0 = time.perf_counter()
            tb, tbx, tby = render_time_block(1920, 1080, layout, "", data["date_text"], data["time_text"])
            t1 = time.perf_counter()
            breakdown["time_block_render"].append((t1 - t0) * 1000.0)

            if tb:
                t0 = time.perf_counter()
                rotated_paste(img, tb, tbx + tb.width//2, tby + tb.height//2, 0, cache_key="time_block")
                t1 = time.perf_counter()
                breakdown["time_block_paste"].append((t1 - t0) * 1000.0)

        # 4. Indicators
        for k, ind_cfg in layout.get("indicators", {}).items():
            if k in ("time_block", "time_display") or not ind_cfg.get("enabled", True):
                continue
            
            # render indicator
            t0 = time.perf_counter()
            # extract val
            val_tuple = data.get(k)
            # simulate known_vals resolution
            val = 50.0
            unit = ind_cfg.get("unit", "")
            label = ind_cfg.get("label", k)
            formatted_val = f"{val:.1f} {unit}"
            res, rx, ry, extra = render_value_indicator(
                1920, 1080, layout, "",
                k, val, unit, label,
                cfg_override=ind_cfg,
                formatted_val=formatted_val,
                history_data=None,
                gps_track=fit_data.get("track"),
                supersample=1,
                target_dt=current_dt,
            )
            t1 = time.perf_counter()
            breakdown["indicators_render"][k].append((t1 - t0) * 1000.0)

            if res:
                t0 = time.perf_counter()
                rotated_paste(img, res, rx + res.width//2, ry + res.height//2, 0, cache_key=k)
                t1 = time.perf_counter()
                breakdown["indicators_paste"][k].append((t1 - t0) * 1000.0)

    print(f"{'Component':30s} | {'Render Avg ms':13s} | {'Paste Avg ms':12s} | {'Total Avg ms':12s} | {'% of Frame':10s}")
    print("-" * 88)
    frame_avg = statistics.mean(export_frame_times)

    t_prep_avg = statistics.mean(breakdown["telemetry_prep"])
    print(f"{'Telemetry lookup & prep':30s} | {t_prep_avg:13.2f} | {'-':12s} | {t_prep_avg:12.2f} | {t_prep_avg/frame_avg*100:9.1f}%")

    t_clear_avg = statistics.mean(breakdown["canvas_clear"])
    print(f"{'Canvas regional clear':30s} | {t_clear_avg:13.2f} | {'-':12s} | {t_clear_avg:12.2f} | {t_clear_avg/frame_avg*100:9.1f}%")

    if breakdown["time_block_render"]:
        tb_r = statistics.mean(breakdown["time_block_render"])
        tb_p = statistics.mean(breakdown["time_block_paste"]) if breakdown["time_block_paste"] else 0
        print(f"{'time_block':30s} | {tb_r:13.2f} | {tb_p:12.2f} | {tb_r+tb_p:12.2f} | {(tb_r+tb_p)/frame_avg*100:9.1f}%")

    for k in layout.get("indicators", {}):
        if k in ("time_block", "time_display"):
            continue
        r_list = breakdown["indicators_render"][k]
        p_list = breakdown["indicators_paste"][k]
        if r_list:
            r_avg = statistics.mean(r_list)
            p_avg = statistics.mean(p_list) if p_list else 0
            tot = r_avg + p_avg
            print(f"{k:30s} | {r_avg:13.2f} | {p_avg:12.2f} | {tot:12.2f} | {tot/frame_avg*100:9.1f}%")

    # ─────────────────────────────────────────────────────────────
    # PART 3: PROFILING ADVANCED INDICATORS (GAUGE, CHART, MAP)
    # ─────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("PART 3: BENCHMARK OF HEAVY INDICATOR TYPES")
    print("="*70)
    
    # 3.A Gauge indicator (speed_visual as gauge)
    gauge_cfg = {"form": "gauge", "enabled": True, "x": 0.1, "y": 0.1, "size": 0.25, "min_val": 0, "max_val": 100, "thickness": 2}
    gauge_times = []
    for _ in range(30):
        t0 = time.perf_counter()
        res, _, _, _ = render_value_indicator(
            1920, 1080, layout, "", "speed_gauge", 45.0, "km/h", "Speed",
            cfg_override=gauge_cfg, formatted_val="45.0 km/h", supersample=1
        )
        t1 = time.perf_counter()
        gauge_times.append((t1 - t0) * 1000.0)
    print(f"Circular Gauge (gauge): avg={statistics.mean(gauge_times):.2f} ms | p95={statistics.quantiles(gauge_times, n=20)[18]:.2f} ms")

    # 3.B History Chart indicator (with 300 data points)
    hist_data = [math.sin(x/10.0)*30 + 50 for x in range(300)]
    chart_cfg = {"form": "chart", "enabled": True, "x": 0.1, "y": 0.5, "w": 0.3, "h": 0.15, "min_val": 0, "max_val": 100, "chart_scope": "all"}
    chart_times = []
    for _ in range(30):
        t0 = time.perf_counter()
        res, _, _, _ = render_value_indicator(
            1920, 1080, layout, "", "hr_chart", 145.0, "BPM", "HR",
            cfg_override=chart_cfg, formatted_val="145 BPM", history_data=hist_data, current_position=0.5, supersample=1
        )
        t1 = time.perf_counter()
        chart_times.append((t1 - t0) * 1000.0)
    print(f"History Chart (chart, 300 pts): avg={statistics.mean(chart_times):.2f} ms | p95={statistics.quantiles(chart_times, n=20)[18]:.2f} ms")

    # 3.C Map indicator (track_map)
    map_cfg = {"form": "static_map", "enabled": True, "x": 0.7, "y": 0.1, "w": 0.25, "h": 0.25}
    map_times = []
    track_pts = fit_data.get("track", [])
    for _ in range(30):
        t0 = time.perf_counter()
        res, _, _, _ = render_value_indicator(
            1920, 1080, layout, "", "track_map", 0.0, "", "Map",
            cfg_override=map_cfg, gps_track=track_pts, target_dt=anchor_dt, supersample=1
        )
        t1 = time.perf_counter()
        map_times.append((t1 - t0) * 1000.0)
    print(f"Track Map (static_map, {len(track_pts)} pts): avg={statistics.mean(map_times):.2f} ms | p95={statistics.quantiles(map_times, n=20)[18]:.2f} ms")

    # ─────────────────────────────────────────────────────────────
    # PART 4: MULTIPROCESSING SCALING (1 to 31 workers)
    # ─────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("PART 4: MULTIPROCESSING THROUGHPUT (SHM Pool + Workers)")
    print("="*70)
    
    n_frames_test = 150
    frame_size = 1920 * 1080 * 4

    init_args = (
        1920, 1080, "", layout, {}, 0.0,
        iso_samples, exposure_samples, temp_samples,
        None, None, None,
        None, None, None, None,
        fit_data, fit_data.get("track"),
        anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, n_frames_test,
        [], 0, None, None, False,
    )

    worker_counts = [1, 2, 4, 8, 16, 24, 31]
    print(f"{'Workers':8s} | {'Total Time (s)':15s} | {'Throughput (FPS)':18s} | {'Latency/Frame (ms)':20s} | {'Scaling vs 1W':14s}")
    print("-" * 84)

    base_fps = 0.0
    for w in worker_counts:
        n_slots = max(4, w * 2)
        shm_pool = SharedFramePool(n_slots, frame_size)
        shm_names = shm_pool.shm_names()
        
        from concurrent.futures import wait, FIRST_COMPLETED
        t0 = time.perf_counter()
        with ProcessPoolExecutor(
            max_workers=w,
            initializer=_init_worker_with_shm,
            initargs=(shm_names, frame_size, *init_args),
        ) as ex:
            pending = set()
            submitted = 0
            for _ in range(min(n_slots, n_frames_test)):
                slot = shm_pool.acquire()
                pending.add(ex.submit(render_frame_shm_job, (submitted, slot)))
                submitted += 1

            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    idx, slot = fut.result()
                    shm_pool.release(slot)
                while submitted < n_frames_test and len(pending) < n_slots:
                    slot = shm_pool.acquire()
                    pending.add(ex.submit(render_frame_shm_job, (submitted, slot)))
                    submitted += 1
                
        t1 = time.perf_counter()
        shm_pool.close()
        
        elapsed = t1 - t0
        fps = n_frames_test / elapsed
        if w == 1:
            base_fps = fps
        speedup = fps / base_fps if base_fps > 0 else 1.0
        eff_lat = (elapsed * 1000.0) / n_frames_test
        print(f"{w:8d} | {elapsed:15.3f} | {fps:18.1f} | {eff_lat:20.2f} | {speedup:13.2f}x")

if __name__ == "__main__":
    main()
