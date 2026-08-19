import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from bisect import bisect_left, bisect_right

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.gui.telemetry_manager import TelemetryDataManager
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
from src.indicators.chart_builder import build_chart_data, ChartHistory

records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX030120.json"))
tm = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
)
tm.load_gpmf_records(records)
tm.load_fit(root / "Video" / "Poranna_jazda_na_rowerze.fit")

video_start_dt = tm.speed_samples[0][0]  # 2026-08-18 04:46:25.700000+00:00
duration_s = 900 * (1001 / 30000)        # 30.03s for 900 frames, or 180.18s for full video 5395 frames: 5395 * (1001/30000) = 180.013s
full_duration_s = 180.18                 # 3:00.18
video_end_dt = video_start_dt + timedelta(seconds=full_duration_s)

hr_samples = tm.resolve_samples("hr", "fit", "fit_heart_rate_text")
cad_samples = tm.resolve_samples("cad", "fit", "fit_cadence_text")

print(f"Video start: {video_start_dt}, Video end: {video_end_dt}")

# Slice HR and CAD to video range
def slice_samples(samples, start_bound, end_bound):
    ts = [s[0] for s in samples]
    # align tz
    sample_tz = ts[0].tzinfo
    def align(b):
        if b is None: return None
        if sample_tz is None: return b.replace(tzinfo=None)
        if b.tzinfo is None: return b.replace(tzinfo=timezone.utc)
        return b
    st = align(start_bound)
    en = align(end_bound)
    s_idx = bisect_left(ts, st) if st is not None else 0
    e_idx = bisect_right(ts, en) if en is not None else len(ts)
    return ChartHistory([s[1] for s in samples[s_idx:e_idx]], ts[s_idx:e_idx])

hr_chart = slice_samples(hr_samples, video_start_dt, video_end_dt)
cad_chart = slice_samples(cad_samples, video_start_dt, video_end_dt)

print(f"HR chart len: {len(hr_chart)}, first_ts: {hr_chart.timestamps[0]}, last_ts: {hr_chart.timestamps[-1]}")
print(f"CAD chart len: {len(cad_chart)}, first_ts: {cad_chart.timestamps[0]}, last_ts: {cad_chart.timestamps[-1]}")

test_seconds = [0, 14.3, 60, 120, 175, 180]
print("\n--- HR TEST TABLE ---")
for sec in test_seconds:
    target_dt = video_start_dt + timedelta(seconds=sec)
    curr_hr = tm.resolve_value("heart_rate", "fit", target_dt)
    pos = (target_dt - video_start_dt).total_seconds() / full_duration_s
    # marker index
    ci = bisect_right(hr_chart.timestamps, target_dt.replace(tzinfo=None)) - 1
    ci_clamped = max(0, min(len(hr_chart) - 1, ci))
    print(f"sec={sec:5.1f} | count={len(hr_chart):3d} | first_ts={hr_chart.timestamps[0].strftime('%H:%M:%S')} | last_ts={hr_chart.timestamps[-1].strftime('%H:%M:%S')} | curr_HR={curr_hr} | pos={pos:6.4f} | ci={ci_clamped:3d} (val={hr_chart[ci_clamped]})")

print("\n--- CADENCE TEST TABLE ---")
for sec in test_seconds:
    target_dt = video_start_dt + timedelta(seconds=sec)
    curr_cad = tm.resolve_value("cadence", "fit", target_dt)
    pos = (target_dt - video_start_dt).total_seconds() / full_duration_s
    ci = bisect_right(cad_chart.timestamps, target_dt.replace(tzinfo=None)) - 1
    ci_clamped = max(0, min(len(cad_chart) - 1, ci))
    print(f"sec={sec:5.1f} | count={len(cad_chart):3d} | first_ts={cad_chart.timestamps[0].strftime('%H:%M:%S')} | last_ts={cad_chart.timestamps[-1].strftime('%H:%M:%S')} | curr_CAD={curr_cad} | pos={pos:6.4f} | ci={ci_clamped:3d} (val={cad_chart[ci_clamped]})")
