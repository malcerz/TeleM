from PIL import Image
import numpy as np
import sys
sys.path.insert(0, ".")

ref = Image.open("scratch/debug_vert_crop_ref.png")
amd = Image.open("scratch/debug_vert_crop_amd.png")

print(f"ref size: {ref.size}, amd size: {amd.size}")
arr_r = np.array(ref)
arr_a = np.array(amd)

# Check alpha of ref
alpha = arr_r[:, :, 3]
print(f"Active pixels in ref: {np.sum(alpha > 0)}")

# Check what is in AMD image where ref is active
# Specifically, where are the ticks or scale drawn?
print(f"Ref non-zero alpha min Y: {np.where(alpha > 0)[0].min()}, max Y: {np.where(alpha > 0)[0].max()}")

# In amd, check if the vertical bar is shifted, scaled, or if the value was different:
# Let's inspect value passed to alt_text in prepare_overlay_frame_data vs compositor:
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
import json
from datetime import timedelta
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = repo_root / "def_layout.json"

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)
layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

fps = 30000.0 / 1001.0
target_dt = tm.start_dt_utc + timedelta(seconds=150 / fps)

frame_kwargs = prepare_overlay_frame_data(
    layout=layout, target_dt=target_dt, tz_offset_hours=2, start_dt_utc=tm.start_dt_utc,
    speed_samples=tm.speed_samples, track_samples=tm.track_samples, alt_samples=tm.alt_samples,
    iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples, temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data, gps_track=tm.get_gps_track_for_source("fit"), fit_field_plan=fit_field_plan,
)

print(f"alt_text in extra_indicators: {frame_kwargs.get('extra_indicators', {}).get('alt_text')}")
print(f"alt_text in indicator_values: {frame_kwargs.get('indicator_values', {}).get('alt_text')}")
