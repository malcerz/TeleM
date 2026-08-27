import json
import sys
from pathlib import Path

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

prev_box = None
prev_bytes = None
false_skips = 0
true_skips = 0

for idx in range(1131):
    kw = telemetry_cache.lookup(idx)
    c_dt = kw.get("c_dt")
    
    map_img, map_heading_val, map_dst, working_size = render_map_unrotated_working_image(
        canvas_w, canvas_h, layout, "track_map",
        gps_track, target_dt=c_dt, current_position=kw.get("current_position"),
        map_heading=kw.get("map_heading"),
    )
    
    renderers = _shared_map_renderers()
    renderer = next(iter(renderers.values()))
    # In Track-Up mode, draw_marker is False, so crop_box is (grid_key, x1, y1)
    crop_box = renderer._last_crop_key
    cur_bytes = map_img.tobytes("raw", "RGBA")
    
    if crop_box == prev_box:
        if cur_bytes != prev_bytes:
            false_skips += 1
            print(f"ERROR: False skip at frame {idx}!")
        else:
            true_skips += 1
            
    prev_box = crop_box
    prev_bytes = cur_bytes

print(f"Crop box equality test on 1131 frames:")
print(f"  False skips (CRITICAL ERROR if >0): {false_skips}")
print(f"  True skips verified: {true_skips} frames ({(true_skips/1131)*100:.2f}%)")
