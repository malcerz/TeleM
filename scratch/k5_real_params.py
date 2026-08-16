"""ETAP 5K — targeted: real cadence chart value-text region, all three renders.

For frame 30 cadence:
  (1) full chart (split_mode=False) value region  — what the CPU produces
  (2) independent full-canvas text render with the same params
  (3) _render_value_text_tile pasted at local
Prints every parameter so the mismatch cause becomes obvious.
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
from src.indicators.chart import _render_value_text_tile

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

    k = "fit_cadence_text"
    full = np.asarray(cap_a[k]["image"], dtype=np.int16)
    sp = cap_b[k]
    # ---- reconstruct the exact renderer parameters for an independent render
    cfg = compose_layout["indicators"][k]
    from src.indicators.helpers import load_font, s, parse_hex_color
    min_dim = min(W, H)
    fs_val = cfg.get("font_size") if "font_size" in cfg else cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    outline_raw = int(compose_layout["global"].get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    font = load_font(font_path, fs)
    chart_w = 1152
    chart_h = max(40, int(chart_w * 0.4))
    tox = int(round(cfg.get("text_offset_x", 0.0) * chart_w))
    toy = int(round(cfg.get("text_offset_y", 0.0) * chart_h))
    text_color_rgb = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
    text_color = (text_color_rgb[0], text_color_rgb[1], text_color_rgb[2], 255)

    # v_str must be reproduced: use formatted_val if present in kwargs
    fv = kwargs.get("indicator_values", {}).get(k)
    v_str = "???"
    # The full chart's value text is drawn with formatted_val; recover it from
    # the chart renderer's caller: it is fv (already formatted).
    print(f"cfg: font_size={cfg.get('font_size')} fs={fs} outline={outline} "
          f"text_offset_x={cfg.get('text_offset_x')} text_offset_y={cfg.get('text_offset_y')}")
    print(f"tox={tox} toy={toy} text_color={text_color} chart_w={chart_w} chart_h={chart_h}")

    # ---- (3) tile from split payload
    vt = sp["value_tile"]
    vl = sp["value_local"]
    print(f"value_tile size={vt.size if vt else None} local={vl}")

    # ---- (1) full chart value region
    vlx, vly = vl
    vw_, vh_ = vt.size
    region_full = full[vly:vly + vh_, vlx:vlx + vw_] if (vly >= 0) else full[0:vly + vh_, vlx:vlx + vw_]
    # clip negative top
    yoff = max(0, -vly)
    region_full = full[max(0, vly):vly + vh_, max(0, vlx):vlx + vw_]

    # ---- (2) independent full-canvas render: need v_str
    # Recover v_str by checking the format used: f"{value:.1f} {unit}" or formatted_val
    # Reconstruct: the chart renderer receives formatted_val = fv. In frame_kwargs,
    # formatted_val comes from prepare_overlay_frame_data -> indicator_values
    iv = kwargs.get("indicator_values", {})
    print(f"indicator_values keys sample: {dict(list(iv.items())[:5]) if iv else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
