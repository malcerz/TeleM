import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitparse

fit_path = "Video/Jazda_na_rowerze_w_porze_lunchu.fit"
fitfile = fitparse.FitFile(fit_path)

records = list(fitfile.get_messages("record"))
print(f"Total record messages: {len(records)}")

field_counts = {}
field_units = {}
field_samples = {}
field_types = {}

for msg in records:
    for f in msg.fields:
        name = f.name
        val = f.value
        units = getattr(f, "units", None)
        fd = getattr(f, "field_def", None)
        is_dev = isinstance(fd, fitparse.records.DevFieldDefinition)
        
        if name not in field_counts:
            field_counts[name] = 0
            field_units[name] = units
            field_samples[name] = []
            field_types[name] = "dev" if is_dev else "standard"
            
        field_counts[name] += 1
        if val is not None and len(field_samples[name]) < 5:
            field_samples[name].append(val)

print("\n--- ALL FIELDS IN FIT RECORD MESSAGES ---")
for name in sorted(field_counts.keys()):
    t = field_types[name]
    cnt = field_counts[name]
    u = field_units[name]
    s = field_samples[name]
    print(f"{name:<30} | {t:<8} | count={cnt:4d} | units={str(u):<10} | samples={s}")
