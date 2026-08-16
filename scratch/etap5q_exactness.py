"""ETAP 5Q — byte-exactness gate: REFERENCE vs OPTIMIZED compose.

Renders all frames of the production layout in BOTH compose modes in a single
process (toggling ``helpers._COMPOSE_5Q``), using:
  * Config A (pure CPU): full 3840x2160 HUD — every widget pasted (covers the
    gauge centre-text change and proves every other widget is unchanged).
  * Config B (production GPU_SPLIT + GPU gauge): the chart dynamic tiles
    (``value_tile`` / ``cursor_tile`` / ``static``) and the captured gauge
    image — covers the chart ``_render_value_text_tile`` cache change.

Reports per-frame MAE / MAX / mismatching-pixel counts and totals.

PASS = MAE 0, MAX 0, mismatching frames 0 for every compared artifact.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ffmpeg.worker_cache import WORKER_CACHE, init_worker, _resolve_cache_value
from src.gui.layout_manager import resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import (
    build_active_fit_field_plan, prepare_overlay_frame_data,
)
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)

TARGET_FPS = 30000 / 1001
W, H = 3840, 2160
CHART_SLOTS = {"fit_cadence_text": 0, "fit_heart_rate_text": 1}
GAUGE_KEY = "fit_enhanced_speed_text"


def _setup():
    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    tm = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
    )
    tm.load_gpmf_records(records)
    tm.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    tm.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
    track = tm.track_samples
    gps_track = tm.get_gps_track_for_source(
        layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
    )
    init_worker(
        video_width=W, video_height=H, font_path=resolve_font_path("Arial"),
        layout=layout, field_samples={"speed_samples": speed, "track_samples": track,
                                       "alt_samples": altitude},
        max_distance_m=track[-1][1] if track else 0,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
        start_dt_utc=tm.start_dt_utc, tz_offset_hours=2,
        speed_samples=speed, track_samples=track, alt_samples=altitude,
        target_fps=TARGET_FPS, update_rate_step=1, total_overlay_frames=1131,
    )
    fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())
    return tm, layout, speed, altitude, track, gps_track, fit_field_plan


def _make_frame_data_fn(tm, layout, speed, altitude, track, gps_track, fit_field_plan):
    base_dt = tm.start_dt_utc

    def fd(frame_idx):
        curr_dt = base_dt + timedelta(seconds=frame_idx / TARGET_FPS)
        return prepare_overlay_frame_data(
            layout=layout, target_dt=curr_dt, start_dt_utc=base_dt, tz_offset_hours=2,
            speed_samples=speed, track_samples=track, alt_samples=altitude,
            iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples, total_frames=1131,
            current_index=frame_idx, chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
            resolve_cache_value=_resolve_cache_value,
            gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
            gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
            gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
            gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
            _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=fit_field_plan,
            resolve_stats={"calls": 0, "per_field": {}},
        )
    return fd


def _render_config_a(kwargs, font_path):
    """Pure CPU full-HUD render -> full RGBA image (all widgets pasted)."""
    bboxes = {}
    img = compose_overlay(
        canvas_w=W, canvas_h=H, layout=_LAYOUT, font_path=font_path,
        _bboxes=bboxes, **kwargs,
    )
    return img


def _render_config_b(kwargs, font_path):
    """Production GPU_SPLIT + GPU gauge render -> (full img, capture dict)."""
    bboxes = {}
    cap = {}
    img = compose_overlay(
        canvas_w=W, canvas_h=H, layout=_LAYOUT, font_path=font_path,
        _bboxes=bboxes,
        gpu_capture_keys=set(CHART_SLOTS.keys()) | {GAUGE_KEY},
        gpu_capture=cap,
        split_chart_keys=set(CHART_SLOTS.keys()),
        **kwargs,
    )
    return img, cap


def _stats(a, b):
    """Return (mae, max, n_mismatch) for two uint8 RGBA arrays (same shape)."""
    if a.shape != b.shape:
        return None, None, -1
    d = np.abs(a.astype(np.int32) - b.astype(np.int32))
    n = int((d > 0).sum())
    if n == 0:
        return 0.0, 0, 0
    return float(d.mean()), int(d.max()), n


def main() -> int:
    import src.indicators.helpers as helpers
    global _LAYOUT
    frames_total = int(sys.argv[1]) if len(sys.argv) > 1 else 1131

    print("=== ETAP 5Q BYTE-EXACTNESS GATE ===", flush=True)
    tm, layout, speed, altitude, track, gps_track, plan = _setup()
    _LAYOUT = layout
    font_path = resolve_font_path("Arial")
    fd = _make_frame_data_fn(tm, layout, speed, altitude, track, gps_track, plan)

    # Per-artifact accumulators.
    artifacts = {
        "hud_full": {"mae": 0.0, "max": 0, "n_mismatch": 0, "bad_frames": 0},
        "hud_split": {"mae": 0.0, "max": 0, "n_mismatch": 0, "bad_frames": 0},
        "gauge": {"mae": 0.0, "max": 0, "n_mismatch": 0, "bad_frames": 0},
    }
    for k in CHART_SLOTS:
        artifacts[f"chart:{k}:static"] = {"mae": 0.0, "max": 0, "n_mismatch": 0, "bad_frames": 0}
        artifacts[f"chart:{k}:cursor"] = {"mae": 0.0, "max": 0, "n_mismatch": 0, "bad_frames": 0}
        artifacts[f"chart:{k}:value"] = {"mae": 0.0, "max": 0, "n_mismatch": 0, "bad_frames": 0}
        artifacts[f"chart:{k}:value_local"] = {"bad_frames": 0, "n_mismatch": 0}

    bad_frames_total = 0
    for f in range(frames_total):
        kw = fd(f)

        # ---- REFERENCE pass ----
        helpers._COMPOSE_5Q = False
        ref_a = _render_config_a(dict(kw), font_path)
        ref_b_img, ref_b_cap = _render_config_b(dict(kw), font_path)

        # ---- OPTIMIZED pass ----
        helpers._COMPOSE_5Q = True
        opt_a = _render_config_a(dict(kw), font_path)
        opt_b_img, opt_b_cap = _render_config_b(dict(kw), font_path)

        frame_bad = 0

        # Full HUD (Config A)
        mae, mx, n = _stats(np.asarray(ref_a), np.asarray(opt_a))
        art = artifacts["hud_full"]
        if n > 0:
            art["mae"] = max(art["mae"], mae); art["max"] = max(art["max"], mx)
            art["n_mismatch"] += n; art["bad_frames"] += 1; frame_bad += 1

        # Full HUD (Config B — non-captured widgets)
        mae, mx, n = _stats(np.asarray(ref_b_img), np.asarray(opt_b_img))
        art = artifacts["hud_split"]
        if n > 0:
            art["mae"] = max(art["mae"], mae); art["max"] = max(art["max"], mx)
            art["n_mismatch"] += n; art["bad_frames"] += 1; frame_bad += 1

        # Gauge captured image
        g_ref = ref_b_cap[GAUGE_KEY]["image"]
        g_opt = opt_b_cap[GAUGE_KEY]["image"]
        mae, mx, n = _stats(np.asarray(g_ref), np.asarray(g_opt))
        art = artifacts["gauge"]
        if n > 0:
            art["mae"] = max(art["mae"], mae); art["max"] = max(art["max"], mx)
            art["n_mismatch"] += n; art["bad_frames"] += 1; frame_bad += 1

        # Chart tiles
        for k in CHART_SLOTS:
            rc = ref_b_cap[k]
            oc = opt_b_cap[k]
            for tile_name, label in (("static", "static"), ("cursor_tile", "cursor"),
                                     ("value_tile", "value")):
                mae, mx, n = _stats(np.asarray(rc[tile_name]), np.asarray(oc[tile_name]))
                art = artifacts[f"chart:{k}:{label}"]
                if n > 0:
                    art["mae"] = max(art["mae"], mae); art["max"] = max(art["max"], mx)
                    art["n_mismatch"] += n; art["bad_frames"] += 1; frame_bad += 1
            # local offsets must be identical too
            if rc["value_local"] != oc["value_local"] or rc["cursor_local"] != oc["cursor_local"]:
                art = artifacts[f"chart:{k}:value_local"]
                art["bad_frames"] += 1; art["n_mismatch"] += 1; frame_bad += 1

        if frame_bad:
            bad_frames_total += 1
        if f % 200 == 0:
            print(f"  frame {f}/{frames_total} (bad_so_far={bad_frames_total})", flush=True)

    print(f"\nEXACTNESS RESULT ({frames_total} frames):", flush=True)
    ok = True
    for name, art in artifacts.items():
        bad = art["bad_frames"]
        # value_local has no mae/max fields
        if "mae" in art:
            print(f"  {name:34s} MAE={art['mae']:.6f} MAX={art['max']} "
                  f"bad_frames={bad} mismatch_px={art['n_mismatch']}", flush=True)
        else:
            print(f"  {name:34s} bad_frames={bad} mismatch={art['n_mismatch']}", flush=True)
        if bad:
            ok = False
    print(f"  mismatching frames (any artifact): {bad_frames_total}", flush=True)

    # Sanity: the OPT branch must have actually run and populated its caches.
    from src.indicators.helpers import _STATIC_CACHE
    n_gauge = sum(1 for k in _STATIC_CACHE if k[0] == "gauge_value_text")
    n_tile = sum(1 for k in _STATIC_CACHE if k[0] == "value_text_tile")
    print(f"  OPT cache sanity: gauge_value_text entries={n_gauge} "
          f"value_text_tile entries={n_tile}", flush=True)
    if ok and (n_gauge == 0 or n_tile == 0):
        print("  WARNING: OPT branch appears not to have run!", flush=True)
        ok = False

    print(f"\nETAP 5Q EXACTNESS = {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


_LAYOUT = None

if __name__ == "__main__":
    raise SystemExit(main())
