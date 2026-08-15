"""ETAP 5I — find every alpha_composite call, its size and caller, during compose."""
import json
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.telemetry_extract import (
    ensure_records_list, extract_speed_samples, extract_altitude_samples,
    extract_track_samples, extract_iso_samples, extract_exposure_samples,
    extract_temperature_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan

records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
telemetry = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples, extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
)
telemetry.load_gpmf_records(records)
telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
with (ROOT / "def_layout.json").open(encoding="utf-8") as fh:
    layout = json.load(fh)
compose_layout = json.loads(json.dumps(layout))
compose_layout["indicators"].pop("track_map", None)
speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
track = telemetry.track_samples
gps_track = telemetry.get_gps_track_for_source(layout["indicators"]["track_map"].get("source", "fit"))
fit_field_plan = build_active_fit_field_plan(layout, (telemetry.fit_data or {}).keys())
W, H = 3840, 2160
fps = 30000 / 1001
base_dt = telemetry.start_dt_utc


def frame_kwargs(idx):
    return prepare_overlay_frame_data(
        layout=compose_layout, target_dt=base_dt + timedelta(seconds=idx / fps),
        start_dt_utc=base_dt, tz_offset_hours=2, speed_samples=speed,
        track_samples=track, alt_samples=altitude, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        gpx_speed_samples=telemetry.gpx_speed_samples,
        gpx_track_samples=telemetry.gpx_track_samples,
        gpx_alt_samples=telemetry.gpx_alt_samples,
        gpx_power_samples=telemetry.gpx_power_samples,
        gpx_atemp_samples=telemetry.gpx_atemp_samples,
        gpx_hr_samples=telemetry.gpx_hr_samples,
        gpx_cad_samples=telemetry.gpx_cad_samples,
        fit_data=telemetry.fit_data, gps_track=gps_track, total_frames=1131,
        current_index=idx, chart_data={}, fit_field_plan=fit_field_plan,
    )


orig_ac = Image.alpha_composite
calls = []
import time


def profiled(im1, im2, *a, **k):
    t0 = time.perf_counter()
    r = orig_ac(im1, im2, *a, **k)
    ms = (time.perf_counter() - t0) * 1000
    try:
        size = (im2.width, im2.height)
    except Exception:
        size = None
    frame = sys._getframe(1)
    caller = frame.f_code.co_filename.split("/")[-1] + ":" + str(frame.f_lineno) + " " + frame.f_code.co_name
    calls.append((size, ms, caller))
    return r


Image.alpha_composite = profiled

for fi in (300, 301):
    b = {}
    compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout,
                    font_path=str(ROOT / "include" / "mpv"), _bboxes=b, **frame_kwargs(fi))

print("=== alpha_composite calls (frame 300-301, 2 composes) ===")
by = {}
for size, ms, caller in calls:
    key = (size, caller)
    by.setdefault(key, []).append(ms)
print("count:", len(calls))
for (size, caller), times in sorted(by.items(), key=lambda kv: -sum(kv[1])):
    print("  size=%-12s n=%2d total=%.2fms avg=%.3f  caller=%s" % (str(size), len(times), sum(times), sum(times)/len(times), caller))
