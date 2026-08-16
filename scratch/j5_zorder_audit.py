"""ETAP 5J — GATE A: z-order audit for GPU chart compositing.

Composes the real HUD layout (CPU path, all indicators incl. track_map) and
records the *actual* bbox of every active indicator for many frames, then
computes the exact overlap relationships needed to decide whether the two
charts (fit_cadence_text, fit_heart_rate_text) can be moved to a GPU blend:

  - which widgets render BEFORE / AFTER each chart (layout z-order),
  - whether any widget rendered AFTER a chart overlaps its bbox,
  - whether the charts overlap each other,
  - whether the charts overlap the track_map bbox (GPU map is blended into the
    same HUD canvas, so relative order matters too).

The GPU chart fast-path is only safe for a chart when NO widget drawn after it
in Pillow order overlaps it (GPU chart blend runs after the CPU dirty uploads,
so it would incorrectly sit on top of any later-drawn overlap).
"""
from __future__ import annotations

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
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.indicators.moving_map import render_map_working_image


def bbox_overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    oy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ox * oy, (ox, oy)


def main() -> int:
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
    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    gps_track = telemetry.get_gps_track_for_source(layout["indicators"]["track_map"].get("source", "fit"))
    fit_field_plan = build_active_fit_field_plan(layout, (telemetry.fit_data or {}).keys())
    W, H = 3840, 2160
    fps = 30000 / 1001
    base_dt = telemetry.start_dt_utc

    # Active indicator keys in layout iteration order (this IS the Pillow z-order).
    active_keys = [
        k for k, cfg in layout["indicators"].items()
        if cfg and cfg.get("enabled", True)
    ]
    print("Layout z-order (render order):")
    for i, k in enumerate(active_keys):
        print(f"  [{i}] {k}  form={layout['indicators'][k].get('form','text')}")
    print()

    chart_keys = ("fit_cadence_text", "fit_heart_rate_text")

    def frame_kwargs(idx):
        return prepare_overlay_frame_data(
            layout=layout, target_dt=base_dt + timedelta(seconds=idx / fps),
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

    # Collect bboxes over many frames; charts + text positions are static but
    # we still verify there is no frame-to-frame drift.
    bbox_by_key: dict[str, set] = {k: set() for k in active_keys}
    map_dst_samples = set()
    for idx in range(0, 1131, 30):
        b = {}
        compose_overlay(canvas_w=W, canvas_h=H, layout=layout, font_path=str(ROOT / "include" / "mpv"),
                        _bboxes=b, **frame_kwargs(idx))
        for k in active_keys:
            if k in b:
                bbox_by_key[k].add(tuple(int(v) for v in b[k]))
        m_img, m_dst = render_map_working_image(W, H, layout, "track_map", gps_track,
                                                target_dt=base_dt + timedelta(seconds=idx / fps),
                                                current_position=frame_kwargs(idx).get("current_position"))
        if m_img is not None and m_dst is not None:
            map_dst_samples.add(tuple(int(v) for v in m_dst))
    # Clear the persistent canvas state so a second compose pass isn't polluted.
    from src.indicators.compositor import _get_reusable_canvas
    _get_reusable_canvas(W, H)[1].clear()

    print("=== REAL BBOXES (variants across sampled frames) ===")
    final_bbox: dict[str, tuple] = {}
    for k in active_keys:
        variants = bbox_by_key.get(k, set())
        if len(variants) > 1:
            print(f"  !! {k}: {len(variants)} distinct bbox variants: {sorted(variants)}")
        bb = next(iter(variants)) if variants else None
        final_bbox[k] = bb
        print(f"  {k:28} bbox={bb}")
    print(f"  {'track_map(GPU dst)':28} bbox={sorted(map_dst_samples)}")
    if map_dst_samples:
        final_bbox["track_map"] = tuple(sorted(map_dst_samples)[0])
    print()

    # ── Overlap analysis ────────────────────────────────────────────────
    print("=== OVERLAP ANALYSIS ===")
    unsafe: dict[str, str] = {}
    for ck in chart_keys:
        if ck not in final_bbox or final_bbox[ck] is None:
            print(f"  !! chart {ck} had no bbox in sampled frames — cannot audit")
            continue
        cbbox = final_bbox[ck]
        cidx = active_keys.index(ck)
        # widgets rendered AFTER this chart in Pillow z-order
        later = [(k, final_bbox[k]) for k in active_keys[cidx + 1:] if final_bbox.get(k)]
        # including the GPU map (it is blended into the same HUD canvas)
        if "track_map" in final_bbox and active_keys.index("track_map") > cidx:
            later.append(("track_map", final_bbox["track_map"]))
        overlaps = []
        for lk, lb in later:
            area, dims = bbox_overlap(cbbox, lb)
            if area > 0:
                overlaps.append((lk, area, dims, lb))
        print(f"\n  Chart {ck} (index {cidx}) bbox={cbbox}")
        print(f"    rendered AFTER it: {[k for k in active_keys[cidx+1:] if final_bbox.get(k)]}")
        if overlaps:
            print(f"    !! OVERLAPS (unsafe for GPU):")
            for lk, area, dims, lb in overlaps:
                print(f"       with {lk} bbox={lb} overlap={dims} area={area}px")
            unsafe[ck] = "; ".join(f"{lk}({area}px)" for lk, area, _, _ in overlaps)
        else:
            print(f"    no overlap with any later-drawn widget -> GPU SAFE")

    # charts vs each other
    if all(k in final_bbox for k in chart_keys):
        a, b = final_bbox["fit_cadence_text"], final_bbox["fit_heart_rate_text"]
        area, dims = bbox_overlap(a, b)
        print(f"\n  cadence vs HR overlap: {dims} area={area}px")

    print("\n=== CONCLUSION ===")
    if unsafe:
        print("  GPU charts UNSAFE for:", unsafe)
    else:
        print("  All charts GPU SAFE (no overlap with later-drawn widgets).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
