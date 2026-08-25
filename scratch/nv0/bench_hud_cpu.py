"""bench_hud_cpu.py
HUD CPU-only benchmark — renders all 1131 overlay frames without FFmpeg.
Measures: prepare_overlay_frame_data, compose_overlay, total render_overlay_frame, tobytes.
Outputs median/P95/P99 for each stage.
"""
import sys, time, statistics
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

VIDEO_NAME = "GX020079.MP4"
VIDEO_PATH = BASE_DIR / "Video" / VIDEO_NAME
TARGET_FRAMES = 1131

# We need a minimal layout to get the active HUD.
# Use default AppController layout (same as production).
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.ffmpeg.frame_renderer import render_overlay_frame

import subprocess, json, shutil

# Probe video
ffprobe = shutil.which("ffprobe")
probe_cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration,avg_frame_rate",
             "-of", "json", str(VIDEO_PATH)]
result = subprocess.run(probe_cmd, capture_output=True, text=True)
info = json.loads(result.stdout)
stream = info["streams"][0]
duration_s = float(stream["duration"])
num, den = map(int, stream["avg_frame_rate"].split("/"))
fps = num / den

# Build minimal layout (empty indicators — measures baseline overhead)
# For a proper test we use default controller layout
try:
    from src.gui.qt.controller import AppController
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    controller = AppController()
    layout = controller.layout
    print(f"[INFO] Using AppController layout with {len(layout.get('indicators', {}))} indicators")
except Exception as e:
    print(f"[WARN] Could not load AppController ({e}), using minimal layout")
    layout = {"indicators": {}, "custom_texts": []}

total_overlay_frames = TARGET_FRAMES  # 1131

# Init worker cache (same as production)
init_worker(
    3840, 2160,          # overlay_w, overlay_h
    "",                  # font_path
    layout,
    {},                  # field_samples
    None,                # max_distance_m
    None, None, None,    # iso, exposure, temp samples
    None, None, None,    # gpx speed/track/alt
    None, None, None, None,  # gpx power/atemp/hr/cad
    None,                # fit_data
    None,                # gps_track
    None, 0.0,           # start_dt_utc, tz_offset_hours
    [], [], [],          # speed, track, alt samples
    fps, 1, total_overlay_frames,
)

print(f"[BENCH] Rendering {TARGET_FRAMES} HUD frames at 3840x2160 RGBA")
print(f"[BENCH] Measuring: prepare_overlay_frame_data, compose_overlay, tobytes")
print()

t_prepare = []
t_compose = []
t_tobytes = []
t_total = []

for i in range(TARGET_FRAMES):
    t0 = time.perf_counter()

    # Stage 1: prepare_overlay_frame_data
    t1 = time.perf_counter()
    from datetime import datetime, timezone, timedelta
    t_start = datetime(1970, 1, 1, tzinfo=timezone.utc)
    target_dt = t_start + timedelta(seconds=i / fps)
    data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=0.0,
        start_dt_utc=t_start,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        iso_samples=[],
        exposure_samples=[],
        temperature_samples=[],
        gpx_speed_samples=None,
        gpx_track_samples=None,
        gpx_alt_samples=None,
        gpx_power_samples=None,
        gpx_atemp_samples=None,
        gpx_hr_samples=None,
        gpx_cad_samples=None,
        fit_data=None,
        gps_track=None,
        total_frames=total_overlay_frames,
        current_index=i,
        chart_data={},
        resolve_cache_value=lambda *a, **kw: 0.0,
        _range_cache=None,
    )
    t2 = time.perf_counter()
    t_prepare.append((t2 - t1) * 1000)

    # Stage 2: compose_overlay
    t3 = time.perf_counter()
    img = compose_overlay(
        3840, 2160, layout, "",
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
    t4 = time.perf_counter()
    t_compose.append((t4 - t3) * 1000)

    # Stage 3: tobytes
    t5 = time.perf_counter()
    raw = img.tobytes()
    t6 = time.perf_counter()
    t_tobytes.append((t6 - t5) * 1000)

    t_total.append((t6 - t0) * 1000)

    if i % 100 == 0 or i == TARGET_FRAMES - 1:
        print(f"  Frame {i+1}/{TARGET_FRAMES}  total={t_total[-1]:.1f}ms")

def stats(times, name):
    s = sorted(times)
    n = len(s)
    med = statistics.median(s)
    p95 = s[int(n * 0.95)]
    p99 = s[int(n * 0.99)]
    avg = statistics.mean(s)
    print(f"  {name:35s}  avg={avg:7.2f}ms  median={med:7.2f}ms  P95={p95:7.2f}ms  P99={p99:7.2f}ms")

print()
print("=== HUD CPU BENCHMARK RESULTS ===")
stats(t_prepare, "prepare_overlay_frame_data")
stats(t_compose, "compose_overlay")
stats(t_tobytes, "tobytes (3840x2160 RGBA)")
stats(t_total,   "render_overlay_frame TOTAL")

total_wall = sum(t_total) / 1000.0
hud_fps = TARGET_FRAMES / total_wall
print()
print(f"HUD-only wall time: {total_wall:.2f} s for {TARGET_FRAMES} frames")
print(f"HUD ceiling FPS:    {hud_fps:.2f} FPS")

# Save results
import json
out = {
    "frames": TARGET_FRAMES,
    "hud_only_wall_s": total_wall,
    "hud_ceiling_fps": hud_fps,
    "prepare_median_ms": statistics.median(t_prepare),
    "prepare_p95_ms": sorted(t_prepare)[int(TARGET_FRAMES * 0.95)],
    "prepare_p99_ms": sorted(t_prepare)[int(TARGET_FRAMES * 0.99)],
    "compose_median_ms": statistics.median(t_compose),
    "compose_p95_ms": sorted(t_compose)[int(TARGET_FRAMES * 0.95)],
    "compose_p99_ms": sorted(t_compose)[int(TARGET_FRAMES * 0.99)],
    "tobytes_median_ms": statistics.median(t_tobytes),
    "tobytes_p95_ms": sorted(t_tobytes)[int(TARGET_FRAMES * 0.95)],
    "tobytes_p99_ms": sorted(t_tobytes)[int(TARGET_FRAMES * 0.99)],
    "total_median_ms": statistics.median(t_total),
    "total_p95_ms": sorted(t_total)[int(TARGET_FRAMES * 0.95)],
    "total_p99_ms": sorted(t_total)[int(TARGET_FRAMES * 0.99)],
}
report_dir = BASE_DIR / "Raporty" / "NVIDIA_NV0"
report_dir.mkdir(parents=True, exist_ok=True)
with open(report_dir / "bench_hud_cpu.json", "w") as f:
    json.dump(out, f, indent=2)
print(f"\nResults saved to Raporty/NVIDIA_NV0/bench_hud_cpu.json")
