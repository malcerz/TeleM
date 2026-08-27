import json
import sys
import time
import math
import ctypes
from pathlib import Path
from collections import Counter
import numpy as np

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE
from src.indicators.frame_data import build_active_fit_field_plan
from src.telemetry_precompute import build_telemetry_cache
from src.indicators.moving_map import render_map_unrotated_working_image, _shared_map_renderers
from src.moving_map import track_up_working_size

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = repo_root / "def_layout.json"

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

fps = 30000.0 / 1001.0
canvas_w, canvas_h = 3840, 2160
font_path = "arial.ttf"

gps_track = tm.get_gps_track_for_source(layout.get("indicators", {}).get("track_map", {}).get("source", "fit"))

init_worker(
    video_width=canvas_w, video_height=canvas_h, font_path=font_path,
    layout=layout, field_samples={}, speed_samples=tm.speed_samples,
    track_samples=tm.track_samples, alt_samples=tm.alt_samples,
    iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples, fit_data=tm.fit_data,
    gps_track=gps_track,
    start_dt_utc=tm.start_dt_utc, tz_offset_hours=2.0, target_fps=fps,
)
precomputed_chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})

telemetry_cache = build_telemetry_cache(
    layout=layout, base_dt=tm.start_dt_utc, tz_offset_hours=2.0,
    start_dt_utc=tm.start_dt_utc, speed_samples=tm.speed_samples,
    track_samples=tm.track_samples, alt_samples=tm.alt_samples,
    iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples, fit_data=tm.fit_data,
    gps_track=gps_track,
    chart_data=precomputed_chart_data, fit_field_plan=fit_field_plan,
    total_frames=1131, target_fps=fps,
)

print(f"=== ETAP 4I MAP DETAILED BREAKDOWN (1131 frames) ===")

timings = {
    "total_map_call": [],
    "render_map_inner": [],
    "pos_lookup": [],
    "grid_fetch_or_hit": [],
    "crop_call": [],
    "tobytes_call": [],
    "direct_ptr_calc": [],
}

grid_hits = 0
grid_misses = 0
unique_crops = set()
crop_coords = []
map_bytes_lens = []

# Warmup / preload renderer
_shared_map_renderers().clear()

for idx in range(1131):
    kw = telemetry_cache.lookup(idx)
    c_dt = kw.get("c_dt")
    
    t0 = time.perf_counter()
    
    # Measure breakdown
    t_inner0 = time.perf_counter()
    map_img, map_heading_val, map_dst, working_size = render_map_unrotated_working_image(
        canvas_w, canvas_h, layout, "track_map",
        gps_track, target_dt=c_dt, current_position=kw.get("current_position"),
        map_heading=kw.get("map_heading"),
    )
    t_inner1 = time.perf_counter()
    
    tb0 = time.perf_counter()
    map_bytes = map_img.tobytes("raw", "RGBA")
    tb1 = time.perf_counter()
    
    t_end = time.perf_counter()
    
    timings["total_map_call"].append((t_end - t0) * 1000.0)
    timings["render_map_inner"].append((t_inner1 - t_inner0) * 1000.0)
    timings["tobytes_call"].append((tb1 - tb0) * 1000.0)
    map_bytes_lens.append(len(map_bytes))

def stats(arr):
    a = np.array(arr)
    return f"AVG={a.mean():.3f}ms | MED={np.median(a):.3f}ms | P95={np.percentile(a, 95):.3f}ms | P99={np.percentile(a, 99):.3f}ms | MIN={a.min():.3f}ms | MAX={a.max():.3f}ms"

print(f"Total map_cpu_upload:  {stats(timings['total_map_call'])}")
print(f"  render_map_inner:    {stats(timings['render_map_inner'])}")
print(f"  map_bytes tobytes:   {stats(timings['tobytes_call'])}")
print(f"Map Image Size: {map_img.size} ({map_img.size[0]}x{map_img.size[1]})")
print(f"Map Bytes per frame: {map_bytes_lens[0]} bytes ({map_bytes_lens[0] / 1024 / 1024:.2f} MB)")
print(f"Total Bytes over 1131 frames: {sum(map_bytes_lens) / 1024 / 1024:.2f} MB")
