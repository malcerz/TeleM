"""Identify which widget occupies bbox=(681,763,558,73) at 1080p in v10."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import compose_overlay
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track, smooth_speed_samples,
    interpolate_value, get_rotation_from_metadata, get_container_rotation,
    find_metadata_json, load_json_with_fallback, smooth_speed_values,
    extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.helpers import s

layout = json.load(open(ROOT / "presets" / "cycling_dashboard_v10.json", encoding="utf-8"))
video_path = ROOT / "Video" / "GX010115.MP4"
json_path = ROOT / "Video" / "GX010115.json"
fit_path = ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"

telemetry = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
    get_rotation_meta_fn=get_rotation_from_metadata,
    get_container_rotation_fn=get_container_rotation,
    find_meta_json_fn=find_metadata_json,
    find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
    load_telemetry_fn=lambda *a: None,
    ensure_records_fn=ensure_records_list,
    load_json_fallback_fn=load_json_with_fallback,
    write_records_fn=lambda p, r: None,
    extract_samples_exiftool_fn=lambda f: [],
    extract_altitude_exiftool_fn=lambda f: [],
    extract_gps_track_fn=extract_gps_track,
    find_gps_anchor_fn=lambda r: None,
    smooth_values_fn=smooth_speed_values,
    extract_accelerometer_fn=extract_accelerometer_samples,
    extract_gyroscope_fn=extract_gyroscope_samples,
)
with open(json_path, "r", encoding="utf-8") as f:
    meta = json.load(f)
records = ensure_records_list(meta)
telemetry.load_gpmf_records(records)
telemetry.load_gps_track(records)
telemetry.load_fit(video_path, telemetry.start_dt_utc, manual_path=fit_path)

kw = prepare_overlay_frame_data(
    layout=layout,
    target_dt=telemetry.start_dt_utc,
    start_dt_utc=telemetry.start_dt_utc,
    tz_offset_hours=2.0,
    speed_samples=telemetry.speed_samples,
    track_samples=telemetry.track_samples,
    alt_samples=telemetry.alt_samples,
    iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples,
    temperature_samples=telemetry.temperature_samples,
    total_frames=300,
    current_index=150,
    chart_data={},
    resolve_cache_value=lambda *a, **k: None,
    fit_data=telemetry.fit_data,
    gps_track=telemetry.get_gps_track_for_source("fit"),
    _range_cache=None,
    fit_field_plan={"active_fit_fields": [], "unique_resolve_fields": []},
    resolve_stats=None,
)
bboxes = {}
gpu_capture = {}
keys = set(layout["indicators"]) - {"track_map"}
compose_overlay(
    canvas_w=1920, canvas_h=1080, layout=layout, font_path="",
    _bboxes=bboxes, gpu_capture_keys={"fit_cadence_text", "fit_heart_rate_text"},
    gpu_capture=gpu_capture, render_keys=keys, reuse_canvas=False, **kw,
)
print("=== ALL WIDGET BBOXES at 1080p ===")
for k, b in sorted(bboxes.items(), key=lambda x: (x[1][1], x[1][0])):
    print("  %-26s bbox=%s" % (k, b))
print("\n=== Widgets intersecting (681,763,558,73) ===")
for k, b in bboxes.items():
    bx, by, bw, bh = b
    if bx < 681 + 558 and 681 < bx + bw and by < 763 + 73 and 763 < by + bh:
        print("  %-26s bbox=%s  (overlaps the chart-neighbour box)" % (k, b))
print("\n=== chart capture (probe) ===")
for k, c in gpu_capture.items():
    print("  %-26s bbox=%s rotation=%s split=%s" % (k, c.get("bbox"), c.get("rotation"), c.get("split")))
