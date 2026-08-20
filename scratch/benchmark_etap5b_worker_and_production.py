import sys, os, time, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from datetime import datetime, timedelta
import numpy as np
from PIL import Image

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor,
)
from src.ffmpeg.command_builder import get_layout_hud_regions
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value, _resolve_cache_samples
from src.ffmpeg.shared_memory import SharedFramePool, render_frame_shm_job, _init_worker_with_shm, _SHM_BLOCKS
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.benchmark import BenchmarkTracker

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
n_frames = 1132
target_fps = 29.97

def benchmark_single_worker_precomputed():
    print("======================================================================")
    print("1. BENCHMARKING SINGLE WORKER WITH PRECOMPUTED TELEMETRY (1132 FRAMES)")
    print("======================================================================")
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

    # Initialize worker with precompute cache
    init_worker(
        1920, 1080, "", prod_layout, field_samples, None,
        iso_samples, exposure_samples, temp_samples,
        None, None, None, None, None, None, None,
        fit_data, fit_data.get("track"),
        anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, n_frames,
        None, 0, None, hud_regs, False,
    )
    chart_data = WORKER_CACHE.get("_precomputed_chart_data")
    _range_cache = WORKER_CACHE.get("_prep_cache")

    t0_pre = time.perf_counter()
    cache = build_telemetry_cache(
        layout=prod_layout, base_dt=anchor_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
        chart_data=chart_data, resolve_cache_value=_resolve_cache_value,
        _range_cache=_range_cache, total_frames=n_frames, target_fps=target_fps,
    )
    t_build_s = time.perf_counter() - t0_pre
    WORKER_CACHE["_telemetry_cache"] = cache

    pool = SharedFramePool(1, aw * ah * 4)
    shm_names = pool.shm_names()
    _init_worker_with_shm(shm_names, aw * ah * 4,
        1920, 1080, "", prod_layout, field_samples, None,
        iso_samples, exposure_samples, temp_samples,
        None, None, None, None, None, None, None,
        fit_data, fit_data.get("track"),
        anchor_dt, 0.0,
        speed_samples, track_samples, alt_samples,
        target_fps, 1, n_frames,
        None, 0, None, hud_regs, False, cache
    )

    from src.ffmpeg.frame_renderer import render_overlay_frame

    # Detailed instrumentation per frame
    times_total = []
    times_telemetry = []
    times_compose = []
    times_atlas_crop = []
    times_atlas_alloc = []
    times_atlas_pack = []
    times_numpy = []
    times_shm = []

    rot180 = False
    atlas_w = aw
    atlas_h = ah

    for idx in range(n_frames):
        t_job0 = time.perf_counter_ns()
        
        # 1. Telemetry lookup
        t_t0 = time.perf_counter_ns()
        data = cache.lookup(idx)
        t_t1 = time.perf_counter_ns()

        # 2. Compose
        t_c0 = time.perf_counter_ns()
        from src.indicators.compositor import compose_overlay
        img = compose_overlay(
            1920, 1080, prod_layout, "",
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
        t_c1 = time.perf_counter_ns()

        # 3. Atlas crop & pack
        t_crop0 = time.perf_counter_ns()
        crops = []
        for r in hud_regs:
            dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
            r_crop = img.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
            crops.append((r_crop, atlas_x, atlas_y))
        t_crop1 = time.perf_counter_ns()

        t_alloc0 = time.perf_counter_ns()
        atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
        t_alloc1 = time.perf_counter_ns()

        t_pack0 = time.perf_counter_ns()
        for r_crop, ax, ay in crops:
            atlas_img.paste(r_crop, (ax, ay))
        t_pack1 = time.perf_counter_ns()

        # 4. Numpy view
        t_np0 = time.perf_counter_ns()
        img_arr = np.asarray(atlas_img)
        t_np1 = time.perf_counter_ns()

        # 5. SHM copy
        t_shm0 = time.perf_counter_ns()
        shm_buf = pool.get_memview(0)
        frame_bytes = atlas_h * atlas_w * 4
        shm_arr = np.frombuffer(shm_buf[:frame_bytes], dtype=np.uint8).reshape((atlas_h, atlas_w, 4))
        np.copyto(shm_arr, img_arr)
        t_shm1 = time.perf_counter_ns()

        t_job1 = time.perf_counter_ns()

        times_total.append((t_job1 - t_job0) / 1e6)
        times_telemetry.append((t_t1 - t_t0) / 1e6)
        times_compose.append((t_c1 - t_c0) / 1e6)
        times_atlas_crop.append((t_crop1 - t_crop0) / 1e6)
        times_atlas_alloc.append((t_alloc1 - t_alloc0) / 1e6)
        times_atlas_pack.append((t_pack1 - t_pack0) / 1e6)
        times_numpy.append((t_np1 - t_np0) / 1e6)
        times_shm.append((t_shm1 - t_shm0) / 1e6)

    del shm_arr
    pool.close()

    # Steady state stats (frames 30..1132)
    s_tot = times_total[30:]
    s_tel = times_telemetry[30:]
    s_com = times_compose[30:]
    s_crp = times_atlas_crop[30:]
    s_alc = times_atlas_alloc[30:]
    s_pck = times_atlas_pack[30:]
    s_num = times_numpy[30:]
    s_shm = times_shm[30:]

    stats = {
        "precompute_build_s": t_build_s,
        "total_avg": float(np.mean(s_tot)),
        "total_med": float(np.median(s_tot)),
        "total_p95": float(np.percentile(s_tot, 95)),
        "total_min": float(np.min(s_tot)),
        "total_max": float(np.max(s_tot)),
        "telemetry_avg": float(np.mean(s_tel)),
        "telemetry_med": float(np.median(s_tel)),
        "telemetry_p95": float(np.percentile(s_tel, 95)),
        "compose_avg": float(np.mean(s_com)),
        "compose_med": float(np.median(s_com)),
        "compose_p95": float(np.percentile(s_com, 95)),
        "atlas_crop_avg": float(np.mean(s_crp)),
        "atlas_alloc_avg": float(np.mean(s_alc)),
        "atlas_pack_avg": float(np.mean(s_pck)),
        "atlas_total_avg": float(np.mean(s_crp) + np.mean(s_alc) + np.mean(s_pck)),
        "numpy_avg": float(np.mean(s_num)),
        "shm_avg": float(np.mean(s_shm)),
    }

    print(f"  Worker Job Total:     avg={stats['total_avg']:.3f} ms | med={stats['total_med']:.3f} ms | p95={stats['total_p95']:.3f} ms")
    print(f"  Telemetry Lookup:     avg={stats['telemetry_avg']:.3f} ms ({stats['telemetry_avg']/stats['total_avg']*100:.1f}%) | med={stats['telemetry_med']:.3f} ms")
    print(f"  Compositing:          avg={stats['compose_avg']:.3f} ms ({stats['compose_avg']/stats['total_avg']*100:.1f}%) | med={stats['compose_med']:.3f} ms")
    print(f"  Atlas Crop & Pack:    avg={stats['atlas_total_avg']:.3f} ms ({stats['atlas_total_avg']/stats['total_avg']*100:.1f}%)")
    print(f"  NumPy View:           avg={stats['numpy_avg']:.3f} ms ({stats['numpy_avg']/stats['total_avg']*100:.1f}%)")
    print(f"  SHM Copy:             avg={stats['shm_avg']:.3f} ms ({stats['shm_avg']/stats['total_avg']*100:.1f}%)")
    print(f"  Theoretical 1-Worker: {1000.0/stats['total_avg']:.1f} FPS")
    print(f"  Theoretical 4-Worker: {4000.0/stats['total_avg']:.1f} FPS")

    return stats

def run_3x_production_benchmark():
    print("\n======================================================================")
    print("2. RUNNING 3X FULL PRODUCTION EXPORT BENCHMARKS (RTX 5070 Ti NVENC/NVDEC)")
    print("======================================================================")
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
    out_dir = Path("scratch/benchmark_runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for run_i in range(1, 4):
        out_file = out_dir / f"etap5b_run_{run_i}.mp4"
        if out_file.exists():
            out_file.unlink()

        print(f"\n>>> RUN {run_i} / 3 STARTING...")
        t0 = time.perf_counter()
        duration_s = n_frames / target_fps
        timing_stats = stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg",
            input_files=str(v_file),
            output_file=str(out_file),
            duration_s=duration_s,
            start_dt_utc=anchor_dt,
            tz_offset_hours=0.0,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            font_path="",
            layout=prod_layout,
            field_samples=field_samples,
            target_fps=target_fps,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temp_samples,
            fit_data=fit_data,
            gps_track=fit_data.get("track"),
            encoder="nv",
            workers=4,
            render_w=3840,
            render_h=2160,
            overlay_w=1920,
            overlay_h=1080,
        )
        t1 = time.perf_counter()
        total_time = t1 - t0
        prod_fps = n_frames / total_time
        
        # Extract timing stats from BenchmarkTracker
        tracker = BenchmarkTracker.get_instance()
        stats = tracker.get_summary()
        write_stats = stats.get("ffmpeg_write", {})
        write_avg = write_stats.get("avg", 0.0)
        write_p95 = write_stats.get("p95", 0.0)

        res = {
            "run": run_i,
            "total_time_s": total_time,
            "production_fps": prod_fps,
            "frame_pipe_fps": prod_fps,  # production streaming
            "write_avg_ms": write_avg,
            "write_p95_ms": write_p95,
        }
        results.append(res)
        print(f">>> RUN {run_i} COMPLETED: PRODUCTION = {prod_fps:.1f} FPS ({total_time:.3f} s), ffmpeg_write avg={write_avg:.2f}ms p95={write_p95:.2f}ms")

    return results

if __name__ == "__main__":
    worker_stats = benchmark_single_worker_precomputed()
    prod_runs = run_3x_production_benchmark()

    out_data = {
        "worker_stats": worker_stats,
        "prod_runs": prod_runs,
    }
    with open("scratch/etap5b_benchmark_results.json", "w") as f:
        json.dump(out_data, f, indent=2)
    print("\nSaved full benchmark results to scratch/etap5b_benchmark_results.json")
