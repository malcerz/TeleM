"""ETAP 5I — clean compose_overlay timing (no overlay profiler overhead).

Times compose_overlay directly over many frames and separately measures the
real alpha_composite cost with minimal instrumentation (no per-call lambda
overhead like the overlay profiler adds).
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image
import numpy as np

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


# ---- lightweight Pillow-op + per-widget composite instrumentation ----
import sys as _sys
import src.indicators.compositor as comp_mod
rp_mod = _sys.modules["src.indicators.rotated_paste"]

op_totals = {}   # op name -> [ms, count]
def _wrap(name, fn):
    def w(*a, **k):
        t0 = time.perf_counter()
        r = fn(*a, **k)
        e = op_totals.setdefault(name, [0.0, 0])
        e[0] += (time.perf_counter() - t0) * 1000
        e[1] += 1
        return r
    return w

orig_new = Image.new
Image.new = lambda *a, **k: _wrap("Image.new", orig_new)(*a, **k)
orig_ac = Image.alpha_composite
Image.alpha_composite = _wrap("alpha_composite", orig_ac)

paste_total = {}
orig_rp = rp_mod.rotated_paste
def w_rp(base_img, overlay, center_x, center_y, rotation, prior_bboxes=None, cache_key=None):
    t0 = time.perf_counter()
    r = orig_rp(base_img, overlay, center_x, center_y, rotation, prior_bboxes, cache_key)
    key = str(cache_key)
    e = paste_total.setdefault(key, [0.0, 0])
    e[0] += (time.perf_counter() - t0) * 1000
    e[1] += 1
    return r
comp_mod.rotated_paste = w_rp
# also the module-level reference used by compositor internals
import sys as _sys
sys.modules["src.indicators.rotated_paste"].rotated_paste = w_rp

# warmup + measure
N = 120
times = []
for fi in range(200, 200 + N):
    b = {}
    t0 = time.perf_counter()
    compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout,
                    font_path=str(ROOT / "include" / "mpv"), _bboxes=b, **frame_kwargs(fi))
    times.append((time.perf_counter() - t0) * 1000)

ts = sorted(times)
print("=== CLEAN compose_overlay timing (%d frames, no overlay profiler) ===" % N)
print("  compose_overlay: avg=%.3f med=%.3f p95=%.3f" % (
    sum(ts) / len(ts), ts[len(ts) // 2], ts[int(0.95 * len(ts)) - 1]))
print("\n=== Pillow ops (ms/frame, calls/frame) ===")
for op, (ms, cnt) in sorted(op_totals.items(), key=lambda kv: -kv[1][0]):
    print("  %-16s %.3f ms/frame  %.2f calls/frame" % (op, ms / N, cnt / N))
print("\n=== per-widget final composite (rotated_paste, ms/frame) ===")
for key, (ms, cnt) in sorted(paste_total.items(), key=lambda kv: -kv[1][0]):
    print("  %-26s %.3f ms/frame  %d calls" % (key, ms / N, cnt // N))
