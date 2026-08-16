"""ETAP 5K — diagnose the value-text tile exactness mismatch.

Hypothesis: Pillow ImageDraw.text on RGBA does NOT perform straight-alpha
"over" compositing, so rendering the value text onto a transparent tile and
then alpha-compositing that tile over the static (what the GPU will do) differs
from rendering the text directly over the static (what the CPU does today).

This script renders one chart frame both ways and classifies the diff pixels
by (region, alpha) to pin down the exact cause.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from src.telemetry_extract import (
    ensure_records_list, extract_speed_samples, extract_altitude_samples,
    extract_track_samples, extract_iso_samples, extract_exposure_samples,
    extract_temperature_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan

CHART_KEYS = ("fit_cadence_text", "fit_heart_rate_text")


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
    compose_layout["indicators"].pop("track_map", None)
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

    cap_a = {}
    compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                    _bboxes={}, gpu_capture_keys=set(CHART_KEYS), gpu_capture=cap_a,
                    split_chart_keys=None, reuse_canvas=False, **kwargs)
    cap_b = {}
    compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                    _bboxes={}, gpu_capture_keys=set(CHART_KEYS), gpu_capture=cap_b,
                    split_chart_keys=set(CHART_KEYS), reuse_canvas=False, **kwargs)

    for k in CHART_KEYS:
        full = np.asarray(cap_a[k]["image"], dtype=np.int16)
        sp = cap_b[k]
        static = np.asarray(sp["static"], dtype=np.int16)
        recon = sp["static"].copy()
        if sp["cursor_tile"] is not None:
            recon.paste(sp["cursor_tile"], sp["cursor_local"], sp["cursor_tile"])
        if sp["value_tile"] is not None:
            recon.paste(sp["value_tile"], sp["value_local"], sp["value_tile"])
        recon = np.asarray(recon, dtype=np.int16)
        d = np.abs(full - recon)
        m = d.max(axis=2) > 0
        ys, xs = np.where(m)
        print(f"=== {k}: {int(m.sum())} diff px ===")
        if len(ys) == 0:
            continue
        # Classify: which region (cursor local vs value local) contains each diff px?
        vlx, vly = sp["value_local"]
        vw_, vh_ = sp["value_tile"].size if sp["value_tile"] else (0, 0)
        clx, cly = sp["cursor_local"]
        cw_, ch_ = sp["cursor_tile"].size if sp["cursor_tile"] else (0, 0)
        in_value = (xs >= vlx) & (xs < vlx + vw_) & (ys >= vly) & (ys < vly + vh_)
        in_cursor = (xs >= clx) & (xs < clx + cw_) & (ys >= cly) & (ys < cly + ch_)
        print(f"  in_value_region={int(in_value.sum())} in_cursor_region={int(in_cursor.sum())} other={int((~(in_value | in_cursor)).sum())}")
        print(f"  value_local={sp['value_local']} value_size={sp['value_tile'].size if sp['value_tile'] else None}")
        # Show the first 8 diff pixels: full, static, recon, and tile alpha
        shown = 0
        for y, x in zip(ys, xs):
            if not in_value[y - np.min(ys) if False else 0]:
                pass
            print(f"    ({x},{y}) full={tuple(full[y, x])} static={tuple(static[y, x])} recon={tuple(recon[y, x])}")
            shown += 1
            if shown >= 8:
                break
        # Is the static zero in this region (value over transparent header)?
        vmask = np.zeros_like(m)
        vmask[vly:vly + vh_, vlx:vlx + vw_] = True
        region_static = static[vmask & m]
        if len(region_static) > 0:
            print(f"  static alpha in value-region diff: min={region_static[:, 3].min()} max={region_static[:, 3].max()}")
        # Show the first 10 diff pixels with their static background alpha
        shown = 0
        for y, x in zip(ys, xs):
            in_v = (vlx <= x < vlx + vw_) and (vly <= y < vly + vh_)
            in_c = (clx <= x < clx + cw_) and (cly <= y < cly + ch_)
            where = "value" if in_v else ("cursor" if in_c else "other")
            print(f"    ({x},{y})[{where}] full={tuple(full[y, x])} static={tuple(static[y, x])} recon={tuple(recon[y, x])}")
            shown += 1
            if shown >= 10:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
