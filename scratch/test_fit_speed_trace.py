import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitparse
from telemetry_fit import parse_fit, sync_fit_to_video, FitRecords, FitDataset

fit_path = "Video/Jazda_na_rowerze_w_porze_lunchu.fit"

# 1. Direct parse_fit test
records = parse_fit(fit_path)
print(f"FitRecords loaded: {len(records)} records")
print("FitRecords.field_catalog keys:", sorted(records.field_catalog.keys()))
print("Sample record[0]:", {k: v for k, v in records[0].items() if k in ("timestamp", "speed", "enhanced_speed", "alt", "enhanced_altitude", "distance", "temperature", "heart_rate")})

# 2. Direct sync_fit_to_video test
video_start = records[0]["timestamp"]
fit_dataset = sync_fit_to_video(records, video_start)
print(f"FitDataset fields: {sorted(fit_dataset.keys())}")
print("FitDataset.field_catalog keys:", sorted(fit_dataset.field_catalog.keys()))

# Check enhanced_speed and enhanced_altitude
for test_field in ["enhanced_speed", "speed", "enhanced_altitude", "alt", "heart_rate", "cadence", "distance", "temperature"]:
    samples = fit_dataset.get(test_field)
    cat = fit_dataset.catalog(test_field)
    cnt = len(samples) if samples else 0
    print(f"Field '{test_field:<20}': count={cnt:4d}, cat={cat}")
