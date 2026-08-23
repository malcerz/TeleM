import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telemetry_fit import parse_fit, sync_fit_to_video

fit_path = "Video/Jazda_na_rowerze_w_porze_lunchu.fit"
records = parse_fit(fit_path)
print(f"FitRecords loaded: {len(records)} records")
print("\nFitRecords.field_catalog keys:")
for k in sorted(records.field_catalog.keys()):
    entry = records.field_catalog[k]
    print(f"  {k:<25} | display={entry['display_name']:<25} | unit={entry['unit']:<6} | count={len(entry.get('samples', []))}")

video_start = records[0]["timestamp"]
fit_dataset = sync_fit_to_video(records, video_start)

print(f"\nFitDataset fields count: {len(fit_dataset)}")
print("FitDataset.field_catalog keys:")
for k in sorted(fit_dataset.field_catalog.keys()):
    entry = fit_dataset.field_catalog[k]
    print(f"  {k:<25} | display={entry['display_name']:<25} | unit={entry['unit']:<6} | count={len(entry.get('samples', []))}")
