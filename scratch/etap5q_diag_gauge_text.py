"""ETAP 5Q — quick diagnostic: what is the gauge txt_main / cache key distribution?"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ffmpeg.worker_cache import WORKER_CACHE, init_worker, _resolve_cache_value
from src.gui.layout_manager import resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import (
    build_active_fit_field_plan, prepare_overlay_frame_data,
)
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)

TARGET_FPS = 30000 / 1001
W, H = 3840, 2160

records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
tm = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
)
tm.load_gpmf_records(records)
tm.load_fit(ROOT / "Video" / "Morning_Ride.fit")
tm.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
altitude = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
track = tm.track_samples
gps_track = tm.get_gps_track_for_source(
    layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
)
init_worker(
    video_width=W, video_height=H, font_path=resolve_font_path("Arial"),
    layout=layout, field_samples={"speed_samples": speed, "track_samples": track,
                                   "alt_samples": altitude},
    max_distance_m=track[-1][1] if track else 0,
    iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
    gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
    gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
    gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
    start_dt_utc=tm.start_dt_utc, tz_offset_hours=2,
    speed_samples=speed, track_samples=track, alt_samples=altitude,
    target_fps=TARGET_FPS, update_rate_step=1, total_overlay_frames=1131,
)
plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())
base_dt = tm.start_dt_utc


def fd(i):
    curr_dt = base_dt + timedelta(seconds=i / TARGET_FPS)
    return prepare_overlay_frame_data(
        layout=layout, target_dt=curr_dt, start_dt_utc=base_dt, tz_offset_hours=2,
        speed_samples=speed, track_samples=track, alt_samples=altitude,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples, total_frames=1131,
        current_index=i, chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
        _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=plan,
        resolve_stats={"calls": 0, "per_field": {}},
    )


gcfg = layout["indicators"].get("fit_enhanced_speed_text", {})
print("GAUGE CFG:", json.dumps(gcfg, ensure_ascii=False))

import src.indicators.helpers as helpers
helpers._COMPOSE_5Q = True
cnt = Counter()
bboxes = {}
font_path = resolve_font_path("Arial")
for i in range(1131):
    kw = fd(i)
    bboxes.clear()
    compose_overlay(canvas_w=W, canvas_h=H, layout=layout, font_path=font_path,
                    _bboxes=bboxes, **kw)
    for k in helpers._STATIC_CACHE:
        if k[0] == "gauge_value_text":
            cnt[k] += 1

unique_txt = set(k[1] for k in cnt)
print("unique txt_main count:", len(unique_txt))
print("sample txt_main:", sorted(unique_txt)[:20])
print("total cache entries:", len(cnt))
print("distinct fonts:", len(set(k[2] for k in cnt)),
      "distinct colors:", len(set(k[3] for k in cnt)),
      "distinct outlines:", len(set(k[4] for k in cnt)))
kw0 = fd(0)
print("gauge frame0 value:", kw0.get("value"), "unit:", kw0.get("unit"),
      "formatted:", kw0.get("formatted_val"))
