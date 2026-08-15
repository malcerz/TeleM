"""ETAP 5H — pixel/byte-exact test: REFERENCE vs OPTIMIZED HUD buffer path.

Replicates the two exporter buffer-prep branches (crop->asarray->copyto vs
crop->tobytes->memmove) on real composed HUD frames + adversarial dirty rects.
Requires byte-for-byte identical backing contents.
"""
import ctypes
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    interpolate_value,
    load_json_with_fallback,
    smooth_speed_samples,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.ffmpeg.amd_native_exporter import _dirty_rects_from_bboxes

records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
telemetry = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
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
base_dt = telemetry.start_dt_utc
W, H = 3840, 2160
fps = 30000 / 1001


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


def ref_copy(img, backing_view, rects):
    for x, y, rw, rh in rects:
        region = img.crop((x, y, x + rw, y + rh))
        arr = np.asarray(region, dtype=np.uint8)
        np.copyto(backing_view[y:y + rh, x:x + rw], arr)


def opt_copy(img, backing, backing_view, rects):
    # OPTIMIZED (stride-safe): crop -> tobytes -> frombuffer view -> copyto
    for x, y, rw, rh in rects:
        region = img.crop((x, y, x + rw, y + rh))
        data = region.tobytes("raw", "RGBA")
        arr = np.frombuffer(data, dtype=np.uint8).reshape(rh, rw, 4)
        np.copyto(backing_view[y:y + rh, x:x + rw], arr)


def make_backing():
    backing = (ctypes.c_uint8 * (W * H * 4))()
    view = np.ctypeslib.as_array(backing).reshape((H, W, 4))
    return backing, view


fail = 0
# ---- Real frames: compare backing after dirty-rect copy ----
print("=== REAL FRAMES (byte-exact REF vs OPT) ===")
prev_bboxes = {}
img = None
for fi in range(300, 320):
    fk = frame_kwargs(fi)
    b = {}
    img = compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout,
                          font_path=str(ROOT / "include" / "mpv"), _bboxes=b, **fk)
    rects = _dirty_rects_from_bboxes(prev_bboxes, b, W, H, 8)
    bA, vA = make_backing()
    bB, vB = make_backing()
    ref_copy(img, vA, rects)
    opt_copy(img, bB, vB, rects)
    same = np.array_equal(np.ctypeslib.as_array(bA), np.ctypeslib.as_array(bB))
    if not same:
        d = np.abs(np.ctypeslib.as_array(bA).astype(np.int16) - np.ctypeslib.as_array(bB).astype(np.int16))
        print("  frame %d: MISMATCH max=%d" % (fi, d.max()))
        fail += 1
    else:
        print("  frame %d: identical (rects=%d)" % (fi, len(rects)))
    prev_bboxes = dict(b)

# ---- Adversarial rects (clipping / stride / 1px / overlap) ----
print("\n=== ADVERSARIAL RECTS (byte-exact, clipping/no overrun) ===")
adv_rects = [
    (0, 0, 1, 1),            # top-left 1px
    (0, 0, 3, 3),            # corner
    (17, 5, 3, 7),           # small odd offset
    (100, 100, 17, 17),      # width 17
    (1000, 1000, 173, 173),  # width 173
    (3000, 500, 691, 691),   # width 691 (map-size)
    (10, 10, 1160, 200),     # width 1160
    (W - 5, H - 5, 5, 5),    # bottom-right 1px clip
    (W - 1, H - 1, 1, 1),    # bottom-right corner
    (W - 50, 0, 100, 50),    # right-edge clip
    (0, H - 50, 50, 100),    # bottom-edge clip
    (W - 50, H - 50, 100, 100),  # corner clip
    (200, 200, 400, 300),    # widget-like
    (150, 100, 500, 400),    # overlapping the above
    (0, 0, W, H),            # full canvas
]
for i, rect in enumerate(adv_rects):
    # clip to canvas (native clips; python must not overrun either)
    x, y, rw, rh = rect
    rw = max(0, min(rw, W - x))
    rh = max(0, min(rh, H - y))
    if rw <= 0 or rh <= 0:
        continue
    rect = (x, y, rw, rh)
    bA, vA = make_backing()
    bB, vB = make_backing()
    ref_copy(img, vA, [rect])
    opt_copy(img, bB, vB, [rect])
    same = np.array_equal(np.ctypeslib.as_array(bA), np.ctypeslib.as_array(bB))
    # also verify bytes actually written (non-zero region) and no overrun (outside stays 0)
    written = np.ctypeslib.as_array(bB).reshape((H, W, 4))
    region_nonzero = written[y:y + rh, x:x + rw].any()
    outside = np.ones((H, W, 4), dtype=bool)
    outside[y:y + rh, x:x + rw] = False
    no_overrun = not written[outside].any()
    status = "OK" if same and no_overrun else "FAIL"
    if status == "FAIL":
        fail += 1
    print("  rect %s -> %s  identical=%s region_nonzero=%s no_overrun=%s" % (
        rect, status, same, bool(region_nonzero), no_overrun))

print("\nRESULT:", "PASS" if fail == 0 else "FAIL (%d)" % fail)
