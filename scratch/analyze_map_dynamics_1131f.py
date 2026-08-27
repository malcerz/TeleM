import json
import sys
import time
import hashlib
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

_shared_map_renderers().clear()

hashes = []
headings = []
dsts = []
identical_consecutive = 0
prev_hash = None

for idx in range(1131):
    kw = telemetry_cache.lookup(idx)
    c_dt = kw.get("c_dt")
    
    map_img, map_heading_val, map_dst, working_size = render_map_unrotated_working_image(
        canvas_w, canvas_h, layout, "track_map",
        gps_track, target_dt=c_dt, current_position=kw.get("current_position"),
        map_heading=kw.get("map_heading"),
    )
    
    # Hash bytes
    b = map_img.tobytes("raw", "RGBA")
    h = hashlib.md5(b).hexdigest()
    hashes.append(h)
    headings.append(map_heading_val)
    dsts.append(map_dst)
    
    if h == prev_hash:
        identical_consecutive += 1
    prev_hash = h

unique_hashes = len(set(hashes))
unique_headings = len(set(headings))
unique_dsts = len(set(dsts))

print(f"Total Frames: 1131")
print(f"Unique unrotated map hashes: {unique_hashes} ({(unique_hashes/1131)*100:.1f}%)")
print(f"Consecutive identical unrotated map images: {identical_consecutive} ({(identical_consecutive/1131)*100:.1f}%)")
print(f"Unique headings: {unique_headings}")
print(f"Unique map_dst bboxes: {unique_dsts} ({dsts[0]})")
