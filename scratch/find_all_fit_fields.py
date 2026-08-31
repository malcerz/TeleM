import fitparse
from pathlib import Path
from collections import defaultdict

fit_path = Path(r'C:\_DEV\TeleM\Video\GX010114_116.fit')
fitfile = fitparse.FitFile(str(fit_path))

# Check field_description messages
print("=== FIELD DESCRIPTIONS (Developer Data) ===")
for msg in fitfile.get_messages('field_description'):
    vals = {f.name: f.value for f in msg.fields}
    print(f"Dev field: name={vals.get('field_name')}, units={vals.get('units')}, dev_idx={vals.get('developer_data_index')}, def_num={vals.get('field_definition_number')}")

# Check developer_data_id
print("\n=== DEVELOPER DATA ID ===")
for msg in fitfile.get_messages('developer_data_id'):
    vals = {f.name: f.value for f in msg.fields}
    print(f"Dev ID: {vals}")

# Look at all message types and inspect fields
print("\n=== SEARCHING ALL MESSAGES FOR VOLTAGE / BATTERY / TEMPERATURE ===")
for msg in fitfile.get_messages():
    field_names = [f.name for f in msg.fields]
    for f in msg.fields:
        fn_lower = str(f.name).lower()
        if 'volt' in fn_lower or 'battery' in fn_lower or 'temp' in fn_lower or 'status' in fn_lower:
            if msg.name not in ('record', 'device_info'):
                print(f"Msg: {msg.name} -> field: {f.name} = {f.value} ({f.units})")

# Let's inspect unknown messages specifically
print("\n=== UNKNOWN MESSAGES INVENTORY ===")
unknown_msgs = defaultdict(list)
for msg in fitfile.get_messages():
    if msg.name.startswith('unknown_'):
        unknown_msgs[msg.name].append(msg)

for uname, ulist in sorted(unknown_msgs.items()):
    sample = ulist[0]
    sample_fields = {f.name: (f.value, getattr(f, 'raw_value', None)) for f in sample.fields}
    print(f"{uname} (count={len(ulist)}): sample fields={sample_fields}")
