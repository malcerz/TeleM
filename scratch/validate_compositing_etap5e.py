"""Raw-RGBA equivalence + timing runner for AMD ETAP 5E final compositing.

Modes:
  before   -> run compose_overlay with PIL_COMPOSITE_REFERENCE (profiled)
  after    -> run compose_overlay with PIL_COMPOSITE_OPTIMIZED (profiled)
  compare  -> single-process REFERENCE vs OPTIMIZED byte comparison of the
              full 3840x2160 HUD canvas for all 1131 frames (MAE/MAX/mismatch).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators import compositor
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import build_active_fit_field_plan, prepare_overlay_frame_data
from src.indicators.profiling import get_overlay_profiler
from src.indicators.rotated_paste import set_composite_mode
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)

REF_FRAMES = (0, 30, 300, 600, 900, 1130)
OUT_DIR = ROOT / "Raporty" / "AMD_ETAP5E"


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * percentile / 100.0
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _stats(values: list[float]) -> dict:
    return {
        "avg": statistics.fmean(values) if values else 0.0,
        "median": statistics.median(values) if values else 0.0,
        "p95": _percentile(values, 95), "p99": _percentile(values, 99),
        "frames": len(values),
    }


def load_environment():
    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
    )
    telemetry.load_gpmf_records(records)
    telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    start = datetime(2026, 8, 5, 4, 28, 11)
    telemetry.start_dt_utc = start
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    init_worker(
        3840, 2160, "arial.ttf", layout,
        {"speed_samples": speed, "track_samples": track, "alt_samples": altitude},
        iso_samples=telemetry.iso_samples, exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        gpx_speed_samples=telemetry.gpx_speed_samples,
        gpx_track_samples=telemetry.gpx_track_samples,
        gpx_alt_samples=telemetry.gpx_alt_samples,
        gpx_power_samples=telemetry.gpx_power_samples,
        gpx_atemp_samples=telemetry.gpx_atemp_samples,
        gpx_hr_samples=telemetry.gpx_hr_samples,
        gpx_cad_samples=telemetry.gpx_cad_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.fit_gps_track,
        start_dt_utc=start, speed_samples=speed, track_samples=track,
        alt_samples=altitude, target_fps=30000 / 1001, total_overlay_frames=1131,
    )
    plan = build_active_fit_field_plan(layout, telemetry.fit_data.keys())
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0",
         str(ROOT / "Video" / "GX020079.mp4")],
        check=True, capture_output=True, text=True,
    )
    pts = [float(v.strip().rstrip(",")) for v in probe.stdout.splitlines() if v.strip()][:1131]
    return telemetry, start, layout, speed, altitude, track, plan, pts


def frame_data(telemetry, start, layout, speed, altitude, track, plan, frame, seconds):
    target = start + timedelta(seconds=seconds)
    return prepare_overlay_frame_data(
        layout=layout, target_dt=target, tz_offset_hours=2,
        start_dt_utc=start, speed_samples=speed, track_samples=track,
        alt_samples=altitude, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.fit_gps_track,
        total_frames=1131, current_index=frame,
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=plan,
    )


def call_compose(layout, data):
    return compose_overlay(
        3840, 2160, layout, "arial.ttf", data["date_text"], data["time_text"],
        data["speed_value"], data["distance_m"], data["max_distance_m"],
        data["alt_value"], data["min_alt"], data["max_alt"],
        data["iso_value"], data["exposure_value"], data["temp_value"],
        indicator_values=data["indicator_values"], max_speed_kmh=data["max_speed_kmh"],
        power_value=data["power_value"], atemp_value=data["atemp_value"],
        hr_value=data["hr_value"], cad_value=data["cad_value"],
        battery_value=data["battery_value"], chart_data=data["chart_data"],
        current_position=data["current_position"], extra_indicators=data["extra_indicators"],
        gps_track=data["gps_track"], target_dt=data["target_dt"],
        start_dt_utc=data["start_dt_utc"], elapsed_seconds=data["elapsed_seconds"],
        avg_speed_kmh=data["avg_speed_kmh"],
    )


def run_profiled(mode: str) -> int:
    telemetry, start, layout, speed, altitude, track, plan, pts = load_environment()
    set_composite_mode("REFERENCE" if mode == "before" else "OPTIMIZED")
    profiler = get_overlay_profiler()
    hashes: list[str] = []
    composite_times: list[float] = []
    for frame, seconds in enumerate(pts):
        data = frame_data(telemetry, start, layout, speed, altitude, track, plan, frame, seconds)
        profiler.start_frame(frame, 3840, 2160)
        t0 = time.perf_counter()
        img = call_compose(layout, data)
        composite_times.append((time.perf_counter() - t0) * 1000.0)
        profiler.finish_frame()
        hashes.append(hashlib.sha256(img.tobytes("raw", "RGBA")).hexdigest())
        if frame in REF_FRAMES:
            img.save(OUT_DIR / f"hud_{mode}_frame_{frame}.png")
    summary = profiler.summary()
    result = {
        "mode": mode, "frames": len(pts), "compose_overlay_ms": _stats(composite_times),
        "canvas_sha256_frames": hashes,
        "profiler": summary,
    }
    (OUT_DIR / f"compositing_{mode}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    per_widget = {}
    for key, metrics in summary.get("metrics", {}).items():
        if key.startswith("indicator.") and key.endswith(".paste_composite"):
            per_widget[key] = {
                "avg_ms": metrics["avg_ms"], "median_ms": metrics["median_ms"],
                "p95_ms": metrics["p95_ms"], "p99_ms": metrics["p99_ms"],
                "calls_per_frame": metrics["avg_calls_per_frame"],
            }
    print(json.dumps({"mode": mode, "compose_overlay_ms": _stats(composite_times),
                      "per_widget_paste_composite": per_widget}, indent=2))
    return 0 if len(pts) == 1131 else 1


def run_compare() -> int:
    telemetry, start, layout, speed, altitude, track, plan, pts = load_environment()
    mismatching_frames: list[dict] = []
    max_mae = 0.0
    max_max = 0
    per_frame = {}
    for frame, seconds in enumerate(pts):
        data = frame_data(telemetry, start, layout, speed, altitude, track, plan, frame, seconds)
        set_composite_mode("REFERENCE")
        img_ref = call_compose(layout, data)
        set_composite_mode("OPTIMIZED")
        img_opt = call_compose(layout, data)
        a = np.asarray(img_ref, dtype=np.uint8)
        b = np.asarray(img_opt, dtype=np.uint8)
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        mae = float(diff.mean())
        mx = int(diff.max())
        per_frame[frame] = {"mae": mae, "max": mx}
        if mx > 0:
            mismatching_frames.append({"frame": frame, "mae": mae, "max": mx})
        max_mae = max(max_mae, mae)
        max_max = max(max_max, mx)
    result = {
        "frames_compared": len(pts),
        "mismatching_frames": len(mismatching_frames),
        "first_mismatches": mismatching_frames[:20],
        "overall_mae": max_mae,
        "overall_max": max_max,
        "per_frame": per_frame,
    }
    (OUT_DIR / "compositing_compare.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "per_frame"}, indent=2))
    ok = len(pts) == 1131 and len(mismatching_frames) == 0 and max_mae == 0.0 and max_max == 0
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("before", "after", "compare"))
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.mode == "compare":
        return run_compare()
    return run_profiled(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
