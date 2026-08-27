import json
import os
import sys
from datetime import timedelta
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.moving_map import render_map_unrotated_working_image, render_map_working_image
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan

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
frame_idx = 150
target_dt = tm.start_dt_utc + timedelta(seconds=frame_idx / fps) if tm.start_dt_utc else None
gps_track = tm.get_gps_track_for_source(layout.get("indicators", {}).get("track_map", {}).get("source", "fit"))

frame_kwargs = prepare_overlay_frame_data(
    layout=layout,
    target_dt=target_dt,
    tz_offset_hours=2,
    start_dt_utc=tm.start_dt_utc,
    speed_samples=tm.speed_samples,
    track_samples=tm.track_samples,
    alt_samples=tm.alt_samples,
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=gps_track,
    fit_field_plan=fit_field_plan,
)

print(f"gps_track length: {len(gps_track) if gps_track else 0}")
print(f"current_position: {frame_kwargs.get('current_position')}")
print(f"map_heading: {frame_kwargs.get('map_heading')}")
print(f"target_dt: {target_dt}")

# Call unrotated
map_img, map_heading_val, map_dst, working_size = render_map_unrotated_working_image(
    3840, 2160, layout, "track_map",
    gps_track, target_dt=target_dt,
    current_position=frame_kwargs.get("current_position"),
    map_heading=frame_kwargs.get("map_heading"),
)
print(f"\nUnrotated map: img={map_img.size if map_img else None}, heading={map_heading_val}, dst={map_dst}, working_size={working_size}")
if map_img:
    map_img.save("scratch/test_unrotated_map_f150.png")
    print("Saved scratch/test_unrotated_map_f150.png")

# Call normal working image
map_img2, map_dst2 = render_map_working_image(
    3840, 2160, layout, "track_map",
    gps_track, target_dt=target_dt,
    current_position=frame_kwargs.get("current_position"),
    map_heading=frame_kwargs.get("map_heading"),
)
print(f"\nRotated map: img={map_img2.size if map_img2 else None}, dst={map_dst2}")
if map_img2:
    map_img2.save("scratch/test_rotated_map_f150.png")
    print("Saved scratch/test_rotated_map_f150.png")
