import sys, os
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.gui.layout_manager import normalize_layout
from telemetry_fit import process_fit
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import find_gps_anchor
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value
from src.telemetry_precompute import build_telemetry_cache
from src.indicators.frame_data import prepare_overlay_frame_data

records = gpmf_to_exiftool_json('Video/GX020079.mp4')[0]
anchor_dt = find_gps_anchor(records)
fit_data = process_fit('Video/Morning_Ride.fit', video_start_dt=anchor_dt)
layout = normalize_layout('def_layout.json', 1920, 1080)

field_samples = {
    "start_dt_utc": anchor_dt,
    "speed_samples": [],
    "track_samples": [],
    "alt_samples": [],
}

init_worker(
    1920, 1080, "", layout, field_samples, None,
    None, None, None, None, None, None, None, None, None, None,
    fit_data, fit_data.get("track"),
    anchor_dt, 0.0,
    [], [], [],
    29.97, 1, 1132,
    None, 0, None, None, False,
)

cache = build_telemetry_cache(
    layout=layout, base_dt=anchor_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
    speed_samples=[], track_samples=[], alt_samples=[], fit_data=fit_data, total_frames=1132,
    resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache")
)

ref = prepare_overlay_frame_data(
    layout=layout, target_dt=anchor_dt, tz_offset_hours=0.0, start_dt_utc=anchor_dt,
    speed_samples=[], track_samples=[], alt_samples=[], fit_data=fit_data, total_frames=1132,
    resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache")
)

pre = cache.lookup(0)

diffs = []
for k in ref:
    if k not in pre:
        diffs.append(f"Missing key: {k}")
    elif ref[k] != pre[k]:
        diffs.append(f"Diff in {k}: ref={ref[k]} vs pre={pre[k]}")

if not diffs:
    print("FRAME 0 IS BIT-EXACT IDENTICAL ACROSS ALL FIELDS!")
else:
    print(f"Found {len(diffs)} diffs in Frame 0:")
    for d in diffs:
        print(" ", d)
