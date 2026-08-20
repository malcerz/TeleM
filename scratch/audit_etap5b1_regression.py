import sys, os, time, json, subprocess
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
from src.ffmpeg.command_builder import get_layout_hud_regions, get_layout_hud_bbox, _build_stream_ffmpeg_cmd
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value, _resolve_cache_samples
from src.ffmpeg.shared_memory import SharedFramePool, render_frame_shm_job, _init_worker_with_shm
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.benchmark import BenchmarkTracker

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
n_frames = 1132
target_fps = 29.97

def prepare_common_data():
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

    # 2-cluster layout that produces the 1112x668 Multi-Region Atlas (ETAP 4B/4C baseline)
    layout = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(layout["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False

    return records, speed_samples, alt_samples, track_samples, iso_samples, exposure_samples, temp_samples, anchor_dt, fit_data, field_samples, layout

def measure_export_run(layout, field_samples, speed_samples, track_samples, alt_samples, iso_samples, exposure_samples, temp_samples, fit_data, anchor_dt, precompute_enabled: bool, run_idx: int):
    out_dir = Path("scratch/audit_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    mode_name = "PRECOMPUTE_ON" if precompute_enabled else "PRECOMPUTE_OFF"
    out_file = out_dir / f"{mode_name}_run_{run_idx}.mp4"
    if out_file.exists():
        out_file.unlink()

    duration_s = n_frames / target_fps
    
    # Toggle precompute environment or parameter
    if not precompute_enabled:
        os.environ["TELEM_DISABLE_PRECOMPUTE"] = "1"
    else:
        os.environ.pop("TELEM_DISABLE_PRECOMPUTE", None)

    BenchmarkTracker.get_instance().reset()
    BenchmarkTracker.get_instance().enable(True)

    t0 = time.perf_counter()
    n_piped = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_file),
        duration_s=duration_s,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=layout,
        field_samples=field_samples,
        target_fps=target_fps,
        update_rate_step=1,
        workers=4,
        encoder="nv",
        gpu=0,
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        rotation_degrees=0,
        container_rotation=0,
        overlay_w=1920,
        overlay_h=1080,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
    )
    t1 = time.perf_counter()
    total_time = t1 - t0
    prod_fps = n_frames / total_time

    # Collect stats
    tracker = BenchmarkTracker.get_instance()
    summary = tracker.get_summary()
    write_stats = summary.get("ffmpeg_write", {})
    write_avg = write_stats.get("avg", 0.0)
    write_p95 = write_stats.get("p95", 0.0)

    aw, ah, regs = get_layout_hud_regions(layout, 1920, 1080, max_regions=3)
    slot_mb = (aw * ah * 4) / (1024 * 1024)

    return {
        "mode": mode_name,
        "run": run_idx,
        "precompute": precompute_enabled,
        "total_time_s": total_time,
        "production_fps": prod_fps,
        "write_avg_ms": write_avg,
        "write_p95_ms": write_p95,
        "atlas_w": aw,
        "atlas_h": ah,
        "regions_count": len(regs),
        "mb_per_frame": slot_mb,
    }

def main():
    print("=" * 80)
    print("ETAP 5B.1: REGRESSION AUDIT & A/B BENCHMARK (PRECOMPUTE OFF vs ON)")
    print("=" * 80)

    records, speed_samples, alt_samples, track_samples, iso_samples, exposure_samples, temp_samples, anchor_dt, fit_data, field_samples, layout = prepare_common_data()

    aw, ah, regs = get_layout_hud_regions(layout, 1920, 1080, max_regions=3)
    bw, bh = get_layout_hud_bbox(layout, 1920, 1080)[2:]
    print(f"\nHUD Geometry Check:")
    print(f"  Global BBox: {bw}x{bh} ({bw*bh/(1920*1080)*100:.1f}%)")
    print(f"  Atlas:       {aw}x{ah} ({aw*ah/(1920*1080)*100:.1f}%, {len(regs)} regions)")
    print(f"  Transport:   {(aw*ah*4)/(1024*1024):.2f} MB/frame")

    # 1. Benchmark A: PRECOMPUTE OFF (3 runs)
    print("\n--- RUNNING 3X BENCHMARK A: PRECOMPUTE OFF (ETAP 4B/4C BASELINE) ---")
    runs_a = []
    for r in range(1, 4):
        res = measure_export_run(layout, field_samples, speed_samples, track_samples, alt_samples, iso_samples, exposure_samples, temp_samples, fit_data, anchor_dt, precompute_enabled=False, run_idx=r)
        runs_a.append(res)
        print(f"  Run {r}: Total = {res['total_time_s']:.3f} s | Prod FPS = {res['production_fps']:.1f} | write avg = {res['write_avg_ms']:.2f} ms | p95 = {res['write_p95_ms']:.2f} ms")

    # 2. Benchmark B: PRECOMPUTE ON (3 runs)
    print("\n--- RUNNING 3X BENCHMARK B: PRECOMPUTE ON (ETAP 5B OPTIMIZED) ---")
    runs_b = []
    for r in range(1, 4):
        res = measure_export_run(layout, field_samples, speed_samples, track_samples, alt_samples, iso_samples, exposure_samples, temp_samples, fit_data, anchor_dt, precompute_enabled=True, run_idx=r)
        runs_b.append(res)
        print(f"  Run {r}: Total = {res['total_time_s']:.3f} s | Prod FPS = {res['production_fps']:.1f} | write avg = {res['write_avg_ms']:.2f} ms | p95 = {res['write_p95_ms']:.2f} ms")

    # Summary JSON
    audit_data = {
        "hud_geometry": {
            "atlas_w": aw, "atlas_h": ah, "regions": len(regs), "mb_per_frame": (aw*ah*4)/(1024*1024),
            "global_bw": bw, "global_bh": bh,
        },
        "runs_precompute_off": runs_a,
        "runs_precompute_on": runs_b,
        "median_off_fps": float(np.median([r["production_fps"] for r in runs_a])),
        "median_off_time": float(np.median([r["total_time_s"] for r in runs_a])),
        "median_off_write": float(np.median([r["write_avg_ms"] for r in runs_a])),
        "median_off_write_p95": float(np.median([r["write_p95_ms"] for r in runs_a])),
        "median_on_fps": float(np.median([r["production_fps"] for r in runs_b])),
        "median_on_time": float(np.median([r["total_time_s"] for r in runs_b])),
        "median_on_write": float(np.median([r["write_avg_ms"] for r in runs_b])),
        "median_on_write_p95": float(np.median([r["write_p95_ms"] for r in runs_b])),
    }

    with open("scratch/audit_etap5b1_results.json", "w") as f:
        json.dump(audit_data, f, indent=2)

    print("\n" + "=" * 80)
    print("A/B COMPARISON SUMMARY (MEDIANS):")
    print(f"  PRECOMPUTE OFF: {audit_data['median_off_fps']:.1f} FPS ({audit_data['median_off_time']:.3f} s) | write avg={audit_data['median_off_write']:.2f} ms, p95={audit_data['median_off_write_p95']:.2f} ms")
    print(f"  PRECOMPUTE ON:  {audit_data['median_on_fps']:.1f} FPS ({audit_data['median_on_time']:.3f} s) | write avg={audit_data['median_on_write']:.2f} ms, p95={audit_data['median_on_write_p95']:.2f} ms")
    speedup = ((audit_data['median_on_fps'] - audit_data['median_off_fps']) / audit_data['median_off_fps']) * 100.0
    print(f"  NET SPEEDUP:    {speedup:+.1f}%")
    print("=" * 80)

if __name__ == "__main__":
    main()
