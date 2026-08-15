"""ETAP 5H audit — measure the real HUD buffer-preparation copy chain.

ZERO code changes. Mirrors the exporter's REFERENCE dirty-rect path
(compose_overlay -> crop -> np.asarray -> np.copyto -> backing) with real
indicator bboxes, and measures per-stage cost + candidate optimized paths.
"""
import ctypes
import json
import statistics
import sys
import time
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
from src.indicators.frame_data import prepare_overlay_frame_data
from src.ffmpeg.amd_native_exporter import (
    _dirty_rects_from_bboxes,
)
from src.indicators.frame_data import build_active_fit_field_plan

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
compose_layout["indicators"].pop("track_map", None)  # GPU mode: map removed

speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
track = telemetry.track_samples
gps_track = telemetry.get_gps_track_for_source(
    layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
)
fit_field_plan = build_active_fit_field_plan(layout, (telemetry.fit_data or {}).keys())
base_dt = telemetry.start_dt_utc
W, H = 3840, 2160
fps = 30000 / 1001
max_distance_m = track[-1][1] if track else 0


def make_frame_kwargs(frame_idx):
    curr_dt = base_dt + timedelta(seconds=frame_idx / fps)
    return prepare_overlay_frame_data(
        layout=compose_layout,
        target_dt=curr_dt,
        start_dt_utc=base_dt,
        tz_offset_hours=2,
        speed_samples=speed,
        track_samples=track,
        alt_samples=altitude,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        gpx_speed_samples=telemetry.gpx_speed_samples,
        gpx_track_samples=telemetry.gpx_track_samples,
        gpx_alt_samples=telemetry.gpx_alt_samples,
        gpx_power_samples=telemetry.gpx_power_samples,
        gpx_atemp_samples=telemetry.gpx_atemp_samples,
        gpx_hr_samples=telemetry.gpx_hr_samples,
        gpx_cad_samples=telemetry.gpx_cad_samples,
        fit_data=telemetry.fit_data,
        gps_track=gps_track,
        total_frames=1131,
        current_index=frame_idx,
        chart_data={},
        fit_field_plan=fit_field_plan,
    )


# Build two consecutive frames to get real previous/current bboxes
prev_bboxes = {}
bboxes = {}
img = None
for fi in (300, 301):
    fk = make_frame_kwargs(fi)
    _b = {}
    img = compose_overlay(
        canvas_w=W, canvas_h=H, layout=compose_layout,
        font_path=str(ROOT / "include" / "mpv"), _bboxes=_b, **fk
    )
    prev_bboxes = dict(bboxes)
    bboxes = dict(_b)

print("previous bboxes:", {k: v for k, v in prev_bboxes.items()})
print("current  bboxes:", {k: v for k, v in bboxes.items()})

dirty = _dirty_rects_from_bboxes(prev_bboxes, bboxes, W, H, 8)
logical = sum(w * h * 4 for _, _, w, h in dirty)
print("\nDIRTY RECTS:", dirty)
print("rects/frame:", len(dirty), "logical MiB/frame: %.2f" % (logical / 2 ** 20))

# Persistent backing buffer identical to exporter
hud_frame_bytes = W * H * 4
backing = (ctypes.c_uint8 * hud_frame_bytes)()
backing_view = np.ctypeslib.as_array(backing).reshape((H, W, 4))
stride = W * 4


def rect_area(r): return r[2] * r[3]
def rect_union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]),
            max(a[0] + a[2], b[0] + b[2]) - min(a[0], b[0]),
            max(a[1] + a[3], b[1] + b[3]) - min(a[1], b[1]))

def merge_to(rects, target, area_ratio=1.30):
    out = list(rects)
    while len(out) > target:
        best = None
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                u = rect_union(out[i], out[j])
                overlap = max(0, min(out[i][0] + out[i][2], out[j][0] + out[j][2]) - max(out[i][0], out[j][0])) * \
                          max(0, min(out[i][1] + out[i][3], out[j][1] + out[j][3]) - max(out[i][1], out[j][1]))
                src = rect_area(out[i]) + rect_area(out[j]) - overlap
                ratio = rect_area(u) / max(1, src)
                if ratio <= area_ratio and (best is None or ratio < best[0]):
                    best = (ratio, i, j, u)
        if best is None:
            break
        _, i, j, u = best
        out.pop(j); out.pop(i); out.append(u)
    return sorted(out, key=lambda r: (r[1], r[0]))


def bench(label, fn, iters=1000):
    # warmup
    for _ in range(10):
        fn()
    times = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    ts = sorted(times)
    print("  %-42s avg=%.3f med=%.3f p95=%.3f p99=%.3f ms" % (
        label, statistics.fmean(ts), ts[len(ts) // 2],
        ts[int(0.95 * len(ts)) - 1], ts[int(0.99 * len(ts)) - 1]))
    return ts


print("\n=== MICROBENCH (1000 iter, real dirty rects) ===")

# ---- REFERENCE (current exporter path) ----
def ref_path():
    for x, y, rw, rh in dirty:
        region = img.crop((x, y, x + rw, y + rh))
        region_array = np.asarray(region, dtype=np.uint8)
        np.copyto(backing_view[y:y + rh, x:x + rw], region_array)


bench("REFERENCE crop+asarray+copyto", ref_path)

# ---- CORRECTED candidates (byte-exact: rect rows must honour backing stride) ----
# The flat memmove (previous b1/b2) is WRONG: it ignores the 15360-byte backing
# stride and misplaces every rect row after the first.  Verified bug.  The valid
# safe candidates below keep rows at their correct backing offset.

def opt_a():
    # crop -> tobytes -> np.frombuffer (view) -> np.copyto (strided, one call)
    for x, y, rw, rh in dirty:
        region = img.crop((x, y, x + rw, y + rh))
        data = region.tobytes("raw", "RGBA")
        arr = np.frombuffer(data, dtype=np.uint8).reshape(rh, rw, 4)
        np.copyto(backing_view[y:y + rh, x:x + rw], arr)


def opt_b():
    # crop -> tobytes -> per-row ctypes.memmove honouring the backing stride
    s = W * 4
    addr = ctypes.addressof(backing)
    for x, y, rw, rh in dirty:
        region = img.crop((x, y, x + rw, y + rh))
        data = region.tobytes("raw", "RGBA")
        rowlen = rw * 4
        for row in range(rh):
            ctypes.memmove(addr + (y + row) * s + x * 4,
                           data[row * rowlen:(row + 1) * rowlen], rowlen)


bench("OPT crop+tobytes+frombuffer+copyto", opt_a)
bench("OPT crop+tobytes+per-row memmove", opt_b)

# ---- MERGE audit: reduce rect count via cost-based merge ----
print("\n=== MERGE AUDIT (real rects) ===")
for target in (5, 4, 3, 2):
    merged = merge_to(dirty, target)
    log = sum(rect_area(r) * 4 for r in merged) / 2 ** 20
    print("  merge->%d: %d rects, logical=%.2f MiB (%.1f%% vs current), copied(3x)=%.1f MiB" % (
        target, len(merged), log, 100 * log / (logical / 2 ** 20), 3 * log))


# per-stage breakdown for REFERENCE
print("\n=== REFERENCE PER-STAGE (avg over %d rects, 500 iter) ===" % len(dirty))
stage_crop, stage_arr, stage_copy = [], [], []
for _ in range(500):
    for x, y, rw, rh in dirty:
        t0 = time.perf_counter(); region = img.crop((x, y, x + rw, y + rh)); t1 = time.perf_counter()
        arr = np.asarray(region, dtype=np.uint8); t2 = time.perf_counter()
        np.copyto(backing_view[y:y + rh, x:x + rw], arr); t3 = time.perf_counter()
        stage_crop.append((t1 - t0) * 1000); stage_arr.append((t2 - t1) * 1000); stage_copy.append((t3 - t2) * 1000)
print("  crop:      avg=%.3f ms" % statistics.fmean(stage_crop))
print("  asarray:   avg=%.3f ms" % statistics.fmean(stage_arr))
print("  np.copyto: avg=%.3f ms" % statistics.fmean(stage_copy))
print("  total/rect avg=%.3f ms -> x%d rects = %.2f ms" % (
    statistics.fmean(stage_crop) + statistics.fmean(stage_arr) + statistics.fmean(stage_copy),
    len(dirty), len(dirty) * (statistics.fmean(stage_crop) + statistics.fmean(stage_arr) + statistics.fmean(stage_copy))))
