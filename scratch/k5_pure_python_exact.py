"""ETAP 5K — pure-Python exactness gate for the GPU_SPLIT chart design.

Renders the SAME frame two ways via compose_overlay:
  Mode A (5J): gpu_capture_keys + split_chart_keys=None
      -> gpu_capture[key]["image"] = full 1160x511 chart RGBA (CPU reference).
  Mode B (5K): gpu_capture_keys + split_chart_keys=CHART_KEYS
      -> gpu_capture[key] = ChartSplit payload (static + cursor tile + value tile).
Then reconstructs mode B exactly the way the GPU will assemble it
(straight-alpha "over" per tile, the semantics the 5J shader was validated to
reproduce) and requires MAE 0 / MAX 0 vs mode A.

Usage:
  python scratch/k5_pure_python_exact.py [--frames 0,30,300,600,900,1130]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image
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


def _composite_at(dest_np, tile_img, pos):
    """True straight-alpha 'over' of a tile at an offset (what the GPU shader
    does), using numpy placement + Image.alpha_composite.  Pillow's
    paste(img, pos, img) is NOT used because it pre-multiplies alpha.
    """
    x0, y0 = pos
    th, tw = tile_img.height, tile_img.width
    layer = np.zeros(dest_np.shape, dtype=np.uint8)
    layer[y0:y0 + th, x0:x0 + tw] = np.asarray(tile_img, dtype=np.uint8)
    out = Image.alpha_composite(
        Image.fromarray(dest_np, "RGBA"), Image.fromarray(layer, "RGBA"))
    return np.asarray(out, dtype=np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", default="0,30,300,600,900,1130",
                        help="Comma-separated frame indices to test.")
    parser.add_argument("--all", action="store_true", default=False,
                        help="Test all 1131 frames.")
    args = parser.parse_args()
    if args.all:
        test_frames = list(range(1131))
    else:
        test_frames = [int(x) for x in args.frames.split(",") if x.strip()]

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

    def render_mode(idx, split):
        cap = {}
        compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                        _bboxes={}, gpu_capture_keys=set(CHART_KEYS), gpu_capture=cap,
                        split_chart_keys=set(CHART_KEYS) if split else None,
                        reuse_canvas=False, **frame_kwargs(idx))
        return cap

    overall = True
    dyn_bytes = {k: {"cursor": 0, "value": 0} for k in CHART_KEYS}
    for idx in test_frames:
        cap_a = render_mode(idx, split=False)   # 5J full chart
        cap_b = render_mode(idx, split=True)    # 5K split payload
        line = f"frame {idx:4d}:"
        for k in CHART_KEYS:
            full = cap_a[k]["image"]
            sp = cap_b[k]
            assert sp.get("split"), f"{k} not split!"
            static = sp["static"]
            ct = sp["cursor_tile"]
            vt = sp["value_tile"]
            if ct is not None:
                dyn_bytes[k]["cursor"] = max(dyn_bytes[k]["cursor"], ct.width * ct.height * 4)
            if vt is not None:
                dyn_bytes[k]["value"] = max(dyn_bytes[k]["value"], vt.width * vt.height * 4)
            # GPU assembly simulation: the dynamic tiles are pre-composited
            # over the static on the CPU and the GPU REPLACES their region in
            # the HUD canvas (after blending the static).  Plain replacement —
            # exactly what the native replace mode does.
            recon = np.asarray(sp["static"], dtype=np.uint8).copy()
            if ct is not None:
                x0, y0 = sp["cursor_local"]
                recon[y0:y0 + ct.height, x0:x0 + ct.width] = np.asarray(ct, dtype=np.uint8)
            if vt is not None:
                x0, y0 = sp["value_local"]
                recon[y0:y0 + vt.height, x0:x0 + vt.width] = np.asarray(vt, dtype=np.uint8)
            full_np = np.asarray(full, dtype=np.int16)
            recon_np = recon.astype(np.int16)
            recon_np = np.asarray(recon, dtype=np.int16)
            d = np.abs(full_np - recon_np)
            mae = float(d.mean())
            mx = int(d.max())
            n_diff = int((d.max(axis=2) > 0).sum())
            ok = mae == 0.0 and mx == 0
            overall &= ok
            line += (f"  {k}: MAE={mae:.3f} MAX={mx} diff_px={n_diff}"
                     f" cursor_bbox={ct.size if ct else None}@{sp['cursor_local']}"
                     f" value_bbox={vt.size if vt else None}@{sp['value_local']}"
                     f" {'OK' if ok else 'DIFF'}")
        print(line, flush=True)

    print()
    print("=== GPU_SPLIT pure-Python exactness ===")
    for k in CHART_KEYS:
        cb = dyn_bytes[k]["cursor"]
        vb = dyn_bytes[k]["value"]
        total = cb + vb
        print(f"  {k}: max cursor {cb} B + max value {vb} B = {total} B/frame "
              f"({total / (1024 * 1024):.4f} MiB/frame)")
    print("RESULT:", "PASS-EXACT" if overall else "FAIL")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
