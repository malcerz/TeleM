import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime
from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.indicator_schemas import BUILTIN_FIELDS, get_value_schema
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.dispatcher import render_value_indicator

fit_path = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
video_path = Path("Video/GX010115.MP4")

from src.telemetry_extract import interpolate_value

tm = TelemetryDataManager(interpolate_fn=interpolate_value)
loaded = tm.load_fit(video_path, manual_path=fit_path)
print(f"1. FIT loaded: {loaded}")
print(f"2. fit_data keys ({len(tm.fit_data)}): {sorted(tm.fit_data.keys())}")
print(f"3. available_fit_fields: {sorted(tm.available_fit_fields)}")

# Check each of the target fields in fit_data
target_fields = ["temperature", "solar", "solar_pct", "curVpower", "battery", "battery_pct"]
print("\n--- Target fields in fit_data ---")
for f in target_fields:
    samples = tm.fit_data.get(f)
    if samples:
        vals = [v for _, v in samples if v is not None]
        print(f"  {f:15}: {len(samples)} samples, non-null={len(vals)}, min={min(vals) if vals else None}, max={max(vals) if vals else None}")
    else:
        print(f"  {f:15}: NOT IN fit_data!")

layout = {"version": 10, "indicators": {}}
registered = tm.register_fit_fields(layout, BUILTIN_FIELDS, get_value_schema)
print(f"\n4. Registered FIT keys ({len(registered)}): {registered}")

# Let's inspect data streams discovered by IndicatorMixin
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin
class DummyController(IndicatorMixin):
    def __init__(self, tm):
        self.telemetry = tm
        self.layout = layout

ctrl = DummyController(tm)
streams = ctrl._discover_data_streams()
print(f"\n5. Discovered streams count: {len(streams)}")
stream_keys = {s.key: s for s in streams}
for f in target_fields:
    key = f"fit_{f}_text"
    if key in stream_keys:
        s = stream_keys[key]
        print(f"  Stream {key:20}: display='{s.display_name}', source='{s.source}', unit='{s.unit}', range={s.value_range}, samples={s.sample_count}")
    else:
        print(f"  Stream {key:20}: NOT IN discovered streams!")

# Let's test _on_stream_clicked / _create_indicator for each
print("\n6. Testing _create_indicator for target fields:")
for f in target_fields:
    key = f"fit_{f}_text"
    try:
        ctrl._create_indicator(key)
        cfg = layout["indicators"].get(key)
        print(f"  Created {key:20}: form={cfg.get('form')}, label='{cfg.get('label')}', min={cfg.get('min_val')}, max={cfg.get('max_val')}, source={cfg.get('source')}")
    except Exception as e:
        print(f"  FAILED to create {key:20}: {e}")

# Let's test resolver and prepare_overlay_frame_data at sample timestamp
t0 = tm.fit_data["speed"][0][0]
print(f"\n7. Testing frame_data resolution at t={t0}:")
frame_data = prepare_overlay_frame_data(
    layout=layout,
    target_dt=t0,
    tz_offset_hours=0.0,
    start_dt_utc=t0,
    speed_samples=tm.fit_data.get("speed", []),
    track_samples=tm.fit_data.get("track", []),
    alt_samples=tm.fit_data.get("alt", []),
    fit_data=tm.fit_data,
    resolve_cache_value=lambda field, src, dt, ind_key=None: tm.resolve_value(field, dt, source=src, indicator_key=ind_key),
)

extra_inds = frame_data.get("extra_indicators", {})
for f in target_fields:
    key = f"fit_{f}_text"
    res = extra_inds.get(key)
    print(f"  extra_indicators[{key:20}]: {res}")
