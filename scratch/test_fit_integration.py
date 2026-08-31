import sys
from pathlib import Path
sys.path.insert(0, r'C:\_DEV\TeleM-integration')

from telemetry_fit import parse_fit, sync_fit_to_video

fit_path = Path(r'C:\_DEV\TeleM\Video\GX010114_116.fit')
records = parse_fit(fit_path)
print("parse_fit returned:", type(records))
if records:
    print("Catalog keys:", list(records.field_catalog.keys()))
    dataset = sync_fit_to_video(records, records[0]['timestamp'])
    print("Dataset keys:", list(dataset.keys()))
    for k in ["garmin_battery_voltage", "garmin_battery_percent", "garmin_temperature"]:
        if k in dataset:
            samples = dataset[k]
            print(f"  {k}: {len(samples)} samples, first={samples[0]}, last={samples[-1]}")
