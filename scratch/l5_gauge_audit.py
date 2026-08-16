"""ETAP 5L — Brama A: audit of fit_enhanced_speed_text (speed gauge).

Renders a real frame and reports the gauge's runtime size, bbox, layout index,
z-order, overlaps (vs every other widget + the GPU map dst) and its dirty-bytes
contribution to the CPU HUD upload.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

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
from src.indicators.moving_map import render_map_working_image


def overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def main() -> int:
    idx = 30
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
    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    gps_track = telemetry.get_gps_track_for_source(layout["indicators"]["track_map"].get("source", "fit"))
    fit_field_plan = build_active_fit_field_plan(layout, (telemetry.fit_data or {}).keys())
    W, H = 3840, 2160
    fps = 30000 / 1001
    base_dt = telemetry.start_dt_utc
    font_path = str(ROOT / "include" / "mpv")

    kwargs = prepare_overlay_frame_data(
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

    bboxes = {}
    compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                    _bboxes=bboxes, reuse_canvas=False, **kwargs)

    # Map dst (the GPU map destination in HUD).
    _mimg, map_dst = render_map_working_image(
        W, H, compose_layout, "track_map", gps_track,
        target_dt=kwargs.get("target_dt"),
        current_position=kwargs.get("current_position"),
    )

    key = "fit_enhanced_speed_text"
    gbox = bboxes.get(key)
    print("=== GAUGE AUDIT (frame 30) ===")
    print(f"gauge bbox: {gbox}  size: {gbox[2]}x{gbox[3]} px")
    # layout index
    order = list(compose_layout["indicators"].keys())
    print(f"layout index: {order.index(key)} / {len(order)}")
    print("render order (JSON):")
    for i, k in enumerate(order):
        if k in bboxes:
            print(f"  [{i:2d}] {k} bbox={bboxes[k]}")
    print(f"\nmap dst: {map_dst}")
    print("\noverlaps:")
    all_boxes = {k: v for k, v in bboxes.items()}
    for other, obox in all_boxes.items():
        if other == key:
            continue
        if overlap(gbox, obox):
            print(f"  OVERLAP with {other}: {obox}")
    if map_dst is not None:
        if overlap(gbox, tuple(int(v) for v in map_dst)):
            print(f"  OVERLAP with map dst: {map_dst}")
    # Dirty bytes contribution: full gauge bbox (the dirty upload uses union of
    # dirty rects; gauge alone = its bbox area).
    gw, gh = gbox[2], gbox[3]
    print(f"\ngauge dirty contribution: {gw}*{gh}*4 = {gw*gh*4} B = {gw*gh*4/1024/1024:.3f} MiB/frame")
    # count non-gauge widgets overlapping the gauge region is already reported.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
