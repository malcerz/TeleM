"""All-frame telemetry equivalence check for AMD ETAP 5B."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import (
    build_active_fit_field_plan,
    prepare_overlay_frame_data,
)
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    interpolate_value,
    load_json_with_fallback,
    smooth_speed_samples,
)


def main() -> int:
    video = ROOT / "Video" / "GX020079.mp4"
    records = ensure_records_list(
        load_json_with_fallback(ROOT / "Video" / "GX020079.json")
    )
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
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
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        gpx_speed_samples=telemetry.gpx_speed_samples,
        gpx_track_samples=telemetry.gpx_track_samples,
        gpx_alt_samples=telemetry.gpx_alt_samples,
        gpx_power_samples=telemetry.gpx_power_samples,
        gpx_atemp_samples=telemetry.gpx_atemp_samples,
        gpx_hr_samples=telemetry.gpx_hr_samples,
        gpx_cad_samples=telemetry.gpx_cad_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.fit_gps_track,
        start_dt_utc=start,
        speed_samples=speed,
        track_samples=track,
        alt_samples=altitude,
        target_fps=30000 / 1001,
        total_overlay_frames=1131,
    )
    plan = build_active_fit_field_plan(layout, telemetry.fit_data.keys())

    ffprobe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "frame=best_effort_timestamp_time",
            "-of", "csv=p=0", str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pts = [float(line.strip().rstrip(",")) for line in ffprobe.stdout.splitlines() if line.strip()]
    pts = pts[:1131]
    mismatches: list[dict] = []
    old_calls = 0
    new_stats: dict = {"calls": 0, "per_field": {}}
    old_fit_keys = [
        key for key in layout.get("indicators", {})
        if key.startswith("fit_") and key.endswith("_text")
    ]

    for frame_index, seconds in enumerate(pts):
        target = start + timedelta(seconds=seconds)

        # Reproduce the ETAP 5A resolver workload: five standard aliases plus
        # every registered FIT indicator, including disabled/stale entries.
        before: dict[str, object] = {}
        for field in ("power", "atemp", "hr", "cad", "battery"):
            before[field] = _resolve_cache_value(field, target)
            old_calls += 1
        for key in old_fit_keys:
            field = key[4:-5]
            before[field] = _resolve_cache_value(field, target)
            old_calls += 1

        after = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target,
            tz_offset_hours=2,
            start_dt_utc=start,
            speed_samples=speed,
            track_samples=track,
            alt_samples=altitude,
            iso_samples=telemetry.iso_samples,
            exposure_samples=telemetry.exposure_samples,
            temperature_samples=telemetry.temperature_samples,
            fit_data=telemetry.fit_data,
            gps_track=telemetry.fit_gps_track,
            total_frames=1131,
            current_index=frame_index,
            chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
            resolve_cache_value=_resolve_cache_value,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
            fit_field_plan=plan,
            resolve_stats=new_stats,
        )
        for field in plan["active_fit_fields"]:
            key = f"fit_{field}_text"
            old_value = before[field] or 0.0
            new_value = after["extra_indicators"][key][0]
            if old_value != new_value:
                mismatches.append({
                    "frame": frame_index,
                    "pts": seconds,
                    "field": field,
                    "before": old_value,
                    "after": new_value,
                })

    result = {
        "frames_compared": len(pts),
        "fields_compared": plan["active_fit_fields"],
        "values_compared": len(pts) * len(plan["active_fit_fields"]),
        "mismatched_values": len(mismatches),
        "first_mismatches": mismatches[:20],
        "before_resolve_calls": old_calls,
        "before_calls_per_frame": old_calls / max(1, len(pts)),
        "after_resolve_calls": new_stats["calls"],
        "after_calls_per_frame": new_stats["calls"] / max(1, len(pts)),
        "after_calls_per_field": new_stats["per_field"],
        "fit_field_plan": plan,
    }
    output = ROOT / "Raporty" / "AMD_ETAP5B" / "all_frame_value_comparison.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if len(pts) == 1131 and not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
