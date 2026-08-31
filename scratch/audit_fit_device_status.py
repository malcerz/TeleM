import fitparse
from pathlib import Path
from collections import defaultdict

fit_path = Path(r'C:\_DEV\TeleM\Video\GX010114_116.fit')
fitfile = fitparse.FitFile(str(fit_path))

# Check all messages that contain 'battery' or 'voltage' or 'temp' or 'device'
msg_counts = defaultdict(int)
interesting_msgs = defaultdict(list)

for msg in fitfile.get_messages():
    msg_counts[msg.name] += 1
    field_names = [f.name for f in msg.fields]
    has_battery = any('battery' in str(fn).lower() or 'volt' in str(fn).lower() for fn in field_names)
    has_temp = any('temp' in str(fn).lower() for fn in field_names)
    if has_battery or has_temp or msg.name in ('device_info', 'device_settings'):
        vals = {f.name: (f.value, f.units, getattr(f, 'raw_value', None)) for f in msg.fields}
        interesting_msgs[msg.name].append(vals)

print("=== MESSAGE COUNTS ===")
for name, cnt in sorted(msg_counts.items()):
    print(f"{name}: {cnt}")

print("\n=== INTERESTING MESSAGES FOUND ===")
for name, records in interesting_msgs.items():
    print(f"\nMessage type: '{name}' (total={len(records)})")
    if records:
        print("Field keys in first record:", list(records[0].keys()))
        for i, rec in enumerate(records[:5]):
            print(f"--- Record {i} ---")
            for k, (v, u, rv) in rec.items():
                if v is not None:
                    print(f"  {k}: {v} (unit: {u}, raw: {rv})")
