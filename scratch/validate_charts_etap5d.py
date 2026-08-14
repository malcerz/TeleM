"""Raw-RGBA equivalence runner for AMD ETAP 5D cadence/HR charts."""

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

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators import compositor
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import build_active_fit_field_plan, prepare_overlay_frame_data
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)

KEYS = ("fit_cadence_text", "fit_heart_rate_text")
REF_FRAMES = (0, 30, 300, 600, 900, 1130)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * percentile / 100.0
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _stats(values: list[float]) -> dict:
    return {
        "avg": statistics.fmean(values), "median": statistics.median(values),
        "p95": _percentile(values, 95), "p99": _percentile(values, 99),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("before", "after"))
    args = parser.parse_args()
    out_dir = ROOT / "Raporty" / "AMD_ETAP5D"
    out_dir.mkdir(parents=True, exist_ok=True)

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

    hashes = {key: [] for key in KEYS}
    timings = {key: [] for key in KEYS}
    sizes = {}
    cursor_indices = {key: {} for key in KEYS}
    original = compositor.render_value_indicator

    def capture(*call_args, **call_kwargs):
        key = call_kwargs.get("key") or call_args[4]
        started = time.perf_counter()
        result = original(*call_args, **call_kwargs)
        if key in KEYS:
            image = result[0]
            timings[key].append((time.perf_counter() - started) * 1000.0)
            raw = image.tobytes("raw", "RGBA")
            hashes[key].append(hashlib.sha256(raw).hexdigest())
            sizes[key] = image.size
            frame = len(hashes[key]) - 1
            history = call_kwargs.get("history_data") or []
            position = call_kwargs.get("current_position")
            ci = None if position is None else max(0, min(len(history) - 1, int(round(position * (len(history) - 1)))))
            if frame in REF_FRAMES:
                cursor_indices[key][str(frame)] = ci
                image.save(out_dir / f"{key}_{args.mode}_frame_{frame}.png")
        return result

    compositor.render_value_indicator = capture
    try:
        for frame, seconds in enumerate(pts):
            target = start + timedelta(seconds=seconds)
            data = prepare_overlay_frame_data(
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
            compose_overlay(
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
    finally:
        compositor.render_value_indicator = original

    result = {
        "mode": args.mode, "frames": len(pts), "hashes": hashes,
        "sizes": {k: list(v) for k, v in sizes.items()},
        "indicator_timing_ms": {key: _stats(vals) for key, vals in timings.items()},
        "cursor_indices": cursor_indices,
    }
    path = out_dir / f"chart_widgets_{args.mode}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "hashes"}, indent=2))
    return 0 if len(pts) == 1131 and all(len(hashes[k]) == 1131 for k in KEYS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
