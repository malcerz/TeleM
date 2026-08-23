import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telemetry_fit import parse_fit, sync_fit_to_video

recs = parse_fit("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
print("FitRecords field_catalog keys:")
for k, v in recs.field_catalog.items():
    if "battery" in k:
        print(f"  {k}: display='{v.get('display_name')}', dev_idx={v.get('dev_data_index')}, def_num={v.get('field_def_num')}")

ds = sync_fit_to_video(recs, None)
print("\nFitDataset field_catalog keys:")
for k, v in ds.field_catalog.items():
    if "battery" in k:
        print(f"  {k}: display='{v.get('display_name')}', dev_idx={v.get('dev_data_index')}, def_num={v.get('field_def_num')}")
