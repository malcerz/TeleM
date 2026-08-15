"""Isolated split-timing of the 5G GPU-map CPU work (crop+marker vs tobytes).

Measurement-only scratch (NO production changes). Replicates the exporter's
map block from src/ffmpeg/amd_native_exporter.py (render_map_working_image +
PIL tobytes), using the real track so the numbers are representative.
"""
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ffmpeg.streaming import stream_overlay_to_ffmpeg  # noqa: F401  (imports side effects for numpy etc.)
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
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.moving_map import render_map_working_image

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
telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11, tzinfo=timezone.utc)

with (ROOT / "def_layout.json").open(encoding="utf-8") as fh:
    layout = json.load(fh)

gps_track = telemetry.get_gps_track_for_source(
    layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
)
if not gps_track or len(gps_track) < 2:
    print("NO TRACK")
    raise SystemExit(1)

fps = 30000 / 1001
N = 120
render_times = []
tobytes_times = []
for i in range(N):
    target_dt = telemetry.start_dt_utc + __import__("datetime").timedelta(seconds=i / fps)
    t0 = time.perf_counter()
    map_img, map_dst = render_map_working_image(
        3840, 2160, layout, "track_map",
        gps_track, target_dt=target_dt, current_position=None,
    )
    t1 = time.perf_counter()
    if map_img is None:
        continue
    _ = map_img.tobytes("raw", "RGBA")
    t2 = time.perf_counter()
    render_times.append((t1 - t0) * 1000.0)
    tobytes_times.append((t2 - t1) * 1000.0)

if map_dst:
    print(f"map_dst bbox={tuple(map_dst)}  working_img={map_img.size}")
print(f"n={len(render_times)}")
print("crop+marker (render_map_working_image): avg=%.3f med=%.3f p95=%.3f ms"
      % (statistics.fmean(render_times), statistics.median(render_times),
         sorted(render_times)[int(0.95 * len(render_times)) - 1]))
print("tobytes (692x692 RGBA):                  avg=%.3f med=%.3f p95=%.3f ms"
      % (statistics.fmean(tobytes_times), statistics.median(tobytes_times),
         sorted(tobytes_times)[int(0.95 * len(tobytes_times)) - 1]))
print("sum (crop+marker+tobytes):               avg=%.3f med=%.3f ms"
      % (statistics.fmean([a + b for a, b in zip(render_times, tobytes_times)]),
         statistics.median([a + b for a, b in zip(render_times, tobytes_times)])))
