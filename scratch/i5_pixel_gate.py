"""ETAP 5I — full CPU HUD pixel-exact gate (REFERENCE vs 5I).

Composes every one of the 1131 frames twice (clean-paste OFF then ON) and
compares the full 3840x2160 RGBA CPU HUD canvas byte-for-byte (sha256 of
tobytes).  Required: mismatching frames == 0, MAE == 0, MAX == 0.
"""
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

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
from src.indicators.compositor import compose_overlay, _get_reusable_canvas
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
rp_mod = __import__("sys").modules["src.indicators.rotated_paste"]

rp_mod.set_clean_paste(False)

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


def compose_into(idx, clean):
    rp_mod.set_clean_paste(clean)
    b = {}
    compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout,
                    font_path=str(ROOT / "include" / "mpv"), _bboxes=b, **frame_kwargs(idx))
    canvas, _ = _get_reusable_canvas(W, H)
    return canvas, b


mismatch_frames = 0
total_pix_diff = 0
max_diff = 0
first_bad = None
for idx in range(1131):
    c_off, _ = compose_into(idx, False)
    h_off = hashlib.sha256(c_off.tobytes()).digest()
    c_on, _ = compose_into(idx, True)
    h_on = hashlib.sha256(c_on.tobytes()).digest()
    if h_off != h_on:
        mismatch_frames += 1
        if first_bad is None:
            first_bad = idx
            a = np.asarray(c_off, dtype=np.int16)
            b = np.asarray(c_on, dtype=np.int16)
            d = np.abs(a - b)
            total_pix_diff = int((d > 0).sum())
            max_diff = int(d.max())
    if idx % 200 == 0:
        print("  frame", idx, "mismatches so far:", mismatch_frames, flush=True)

print("\n=== CPU HUD PIXEL-EXACT GATE (1131 frames) ===")
print("  mismatching frames:", mismatch_frames)
print("  first mismatch frame:", first_bad)
print("  total differing pixels (first bad frame):", total_pix_diff)
print("  MAX diff (first bad frame):", max_diff)
print("  RESULT:", "PASS" if mismatch_frames == 0 else "FAIL")
