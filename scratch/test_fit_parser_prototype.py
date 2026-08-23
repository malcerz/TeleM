import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitparse
from datetime import datetime, timezone

fit_path = "Video/Jazda_na_rowerze_w_porze_lunchu.fit"
fitfile = fitparse.FitFile(fit_path)

# 1. Collect field descriptions
dev_field_defs = {}
dev_name_counts = {}
for msg in fitfile.get_messages("field_description"):
    vals = {f.name: f.value for f in msg.fields}
    dev_idx = vals.get("developer_data_index")
    f_num = vals.get("field_definition_number")
    fname = vals.get("field_name")
    funits = vals.get("units")
    if dev_idx is not None and f_num is not None and fname:
        dev_field_defs[(dev_idx, f_num)] = {
            "name": str(fname),
            "units": str(funits) if funits else "",
            "dev_idx": dev_idx,
            "f_num": f_num,
        }
        dev_name_counts[str(fname)] = dev_name_counts.get(str(fname), 0) + 1

print("Developer field names with collisions:", {k: v for k, v in dev_name_counts.items() if v > 1})

# Check if native fields also collide with dev fields
# Native field names in record
native_names = {"timestamp", "distance", "enhanced_altitude", "heart_rate", "temperature", "cadence", "enhanced_speed", "fractional_cadence", "position_lat", "position_long"}

for (dev_idx, f_num), meta in dev_field_defs.items():
    fname = meta["name"]
    is_duplicate = (dev_name_counts.get(fname, 0) > 1) or (fname in native_names)
    meta["is_duplicate"] = is_duplicate
    if is_duplicate:
        meta["unique_key"] = f"{fname}_{dev_idx}_{f_num}"
        meta["display_name"] = f"{fname.replace('_', ' ').title()} [Dev {dev_idx}:{f_num}]"
    else:
        meta["unique_key"] = fname
        meta["display_name"] = fname.replace("_", " ").title()

print("\nResolved Developer Field Identities:")
for k, meta in sorted(dev_field_defs.items()):
    print(f"  Dev {k[0]}:{k[1]} -> unique_key='{meta['unique_key']}', display_name='{meta['display_name']}', units='{meta['units']}'")
