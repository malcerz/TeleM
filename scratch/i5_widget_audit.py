"""ETAP 5I — widget-level audit of composite_final inputs.

Composes real frames and records, for every widget passed to composite_final:
size, content bbox, alpha_min, whether all alpha==0 pixels have RGB==0
(clean transparency), and whether the destination region is transparent.
This determines if the paste fast-path can be safely extended.
"""
import json
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
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.indicators.rotated_paste import composite_final
from src.indicators.compositor import _get_reusable_canvas

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


records_per_widget = {}

_orig_composite_final = composite_final
_calls = [0]


def wrapped(base_img, overlay, x, y, prior_bboxes=None, cache_key=None):
    _calls[0] += 1
    try:
        return _wrapped_inner(base_img, overlay, x, y, prior_bboxes, cache_key)
    except Exception as e:
        print("  WRAPPED ERROR:", repr(e))
        return _orig_composite_final(base_img, overlay, x, y, prior_bboxes, cache_key)


def _wrapped_inner(base_img, overlay, x, y, prior_bboxes=None, cache_key=None):
    key = cache_key if cache_key is not None else (overlay.width, overlay.height)
    a = np.asarray(overlay, dtype=np.uint8)
    alpha = a[..., 3]
    rgb = a[..., :3]
    zero_alpha = alpha == 0
    dirty_zeros = bool(rgb[zero_alpha].any()) if zero_alpha.any() else False
    alpha_min = int(alpha.min())
    bbox = overlay.getbbox()
    # destination transparency check: sample the canvas region under the overlay
    canvas, _ = _get_reusable_canvas(W, H)
    dest = np.asarray(canvas.crop((x, y, x + overlay.width, y + overlay.height)).convert("RGBA"), dtype=np.uint8)
    dest_alpha_max = int(dest[..., 3].max())
    rec = records_per_widget.setdefault(str(key), {
        "size": (overlay.width, overlay.height), "count": 0, "dirty_zeros_seen": False,
        "alpha_min": 255, "bbox": None, "dest_transparent_all": True, "dest_opaque_max": 0,
        "alpha_composite_ms": 0.0, "paste_ms": 0.0,
    })
    rec["count"] += 1
    rec["dirty_zeros_seen"] = rec["dirty_zeros_seen"] or dirty_zeros
    rec["alpha_min"] = min(rec["alpha_min"], alpha_min)
    if bbox is not None:
        rec["bbox"] = bbox if rec["bbox"] is None else rec["bbox"]
    if dest_alpha_max > 0:
        rec["dest_transparent_all"] = False
    rec["dest_opaque_max"] = max(rec["dest_opaque_max"], dest_alpha_max)
    # timing: alpha_composite vs paste for this overlay over transparent canvas
    if rec["count"] <= 5:
        t0 = time.perf_counter()
        for _ in range(20):
            tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            tmp.alpha_composite(overlay, (x, y))
        rec["alpha_composite_ms"] += (time.perf_counter() - t0) * 1000 / 20
        t0 = time.perf_counter()
        for _ in range(20):
            tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            tmp.paste(overlay, (x, y))
        rec["paste_ms"] += (time.perf_counter() - t0) * 1000 / 20
    return _orig_composite_final(base_img, overlay, x, y, prior_bboxes, cache_key)


import sys as _sys
rp = _sys.modules["src.indicators.rotated_paste"]  # module (pkg re-exports shadow the submodule)
from PIL import Image
rp.composite_final = wrapped
# patch the compositor's imported rotated_paste + any direct composite_final ref
import src.indicators.compositor as comp
_orig_rp = comp.rotated_paste
def wrapped_rotated(base_img, overlay, center_x, center_y, rotation, prior_bboxes=None, cache_key=None):
    return _orig_rp(base_img, overlay, center_x, center_y, rotation, prior_bboxes, cache_key)
comp.rotated_paste = wrapped_rotated
if hasattr(comp, "composite_final"):
    comp.composite_final = wrapped

# compose a few frames
for fi in (300, 301, 302, 303, 304):
    b = {}
    try:
        compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout,
                        font_path=str(ROOT / "include" / "mpv"), _bboxes=b, **frame_kwargs(fi))
    except Exception as e:
        print("compose exception:", repr(e))
    print("frame", fi, "bboxes:", {k: v for k, v in b.items()})

print("composite_final calls observed:", _calls[0])
print("=== WIDGET COMPOSITE AUDIT (per composite_final cache_key) ===")
for key, rec in sorted(records_per_widget.items()):
    print("  key=%-28s size=%s n=%d alpha_min=%d dirty_zeros(rgb!=0 @ a=0)=%s bbox=%s dest_transparent=%s dest_opaque_max=%d alpha_composite=%.3fms paste=%.3fms" % (
        key[:28], rec["size"], rec["count"], rec["alpha_min"], rec["dirty_zeros_seen"],
        rec["bbox"], rec["dest_transparent_all"], rec["dest_opaque_max"],
        rec["alpha_composite_ms"], rec["paste_ms"]))
