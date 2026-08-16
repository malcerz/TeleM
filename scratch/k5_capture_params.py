"""ETAP 5K — capture real chart value-text params and compare full vs tile."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image
import src.indicators.dispatcher as dispatcher_mod
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
CAPTURED = {}


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

    original = dispatcher_mod._render_chart_indicator

    def spy(*a, **kw):
        if kw.get("key") in CHART_KEYS and not kw.get("split_mode"):
            CAPTURED[kw["key"]] = dict(kw)
        return original(*a, **kw)

    dispatcher_mod._render_chart_indicator = spy
    try:
        cap_a = {}
        compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                        _bboxes={}, gpu_capture_keys=set(CHART_KEYS), gpu_capture=cap_a,
                        split_chart_keys=None, reuse_canvas=False, **kwargs)
    finally:
        dispatcher_mod._render_chart_indicator = original

    k = "fit_cadence_text"
    cap = CAPTURED[k]
    print("key:", k)
    print("  formatted_val:", cap.get("formatted_val"))
    print("  value:", cap.get("value"), "unit:", cap.get("unit"))
    print("  fs:", cap.get("fs"), "outline:", cap.get("outline"))
    print("  cfg:", {kk: cap["cfg"].get(kk) for kk in
                     ("text_offset_x", "text_offset_y", "text_color", "font_size")})

    from src.indicators.chart import _render_value_text_tile
    from src.indicators.helpers import s
    cfg = cap["cfg"]
    font = cap["font"]
    chart_w = 1152
    chart_h = max(40, int(chart_w * 0.4))
    tox = int(round(cfg.get("text_offset_x", 0.0) * chart_w))
    toy = int(round(cfg.get("text_offset_y", 0.0) * chart_h))
    from src.indicators.helpers import parse_hex_color
    tcrgb = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
    text_color = (tcrgb[0], tcrgb[1], tcrgb[2], 255)
    v_str = cap.get("formatted_val") if cap.get("formatted_val") else f"{cap['value']:.1f} {cap['unit']}"
    print("  computed v_str:", repr(v_str), "tox:", tox, "toy:", toy, "text_color:", text_color)

    tile, lx, ly = _render_value_text_tile(v_str, font, text_color, cap["outline"], chart_w, tox, toy)
    print("  tile:", tile.size if tile else None, "local:", (lx, ly))

    # Now render mode B (split) and reconstruct exactly like the exporter will,
    # to see whether the negative-offset paste reproduces the full chart.
    cap_b = {}
    compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                    _bboxes={}, gpu_capture_keys=set(CHART_KEYS), gpu_capture=cap_b,
                    split_chart_keys=set(CHART_KEYS), reuse_canvas=False, **kwargs)
    sp = cap_b[k]
    recon = sp["static"].copy()
    if sp["cursor_tile"] is not None:
        recon.paste(sp["cursor_tile"], sp["cursor_local"], sp["cursor_tile"])
    if sp["value_tile"] is not None:
        recon.paste(sp["value_tile"], sp["value_local"], sp["value_tile"])
    recon_np = np.asarray(recon, dtype=np.int16)
    full_np = np.asarray(cap_a[k]["image"], dtype=np.int16)
    d = np.abs(recon_np - full_np)
    m = d.max(axis=2) > 0
    print("  RECON vs FULL: diff_px=", int(m.sum()), "MAE=", round(float(d.mean()), 3), "MAX=", int(d.max()))
    if int(m.sum()):
        ys, xs = np.where(m)
        for yy, xx in zip(ys[:8], xs[:8]):
            print("    at", (xx, yy), "full=", tuple(full_np[yy, xx]), "recon=", tuple(recon_np[yy, xx]),
                  "static=", tuple(np.asarray(sp["static"], dtype=np.int16)[yy, xx]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
