import fitparse
from pathlib import Path
from collections import defaultdict

fit_path = Path(r'C:\_DEV\TeleM\Video\GX010114_116.fit')
fitfile = fitparse.FitFile(str(fit_path))

# Inspect all device_info messages and group by device_index or device_type or manufacturer
device_records = defaultdict(list)

for msg in fitfile.get_messages('device_info'):
    vals = {f.name: (f.value, f.units, getattr(f, 'raw_value', None)) for f in msg.fields}
    dev_idx = vals.get('device_index', (None,))[0]
    ts = vals.get('timestamp', (None,))[0]
    device_records[dev_idx].append((ts, vals))

print(f"Total device_info records: {sum(len(v) for v in device_records.values())}")
print(f"Device indices found: {list(device_records.keys())}")

for dev_idx, recs in sorted(device_records.items(), key=lambda x: str(x[0])):
    print(f"\n=== Device Index: {dev_idx} (count={len(recs)}) ===")
    first_ts = recs[0][0]
    last_ts = recs[-1][0]
    first_vals = recs[0][1]
    mfg = first_vals.get('manufacturer', (None,))[0]
    prod = first_vals.get('product', (None,))[0] or first_vals.get('garmin_product', (None,))[0]
    dev_type = first_vals.get('device_type', (None,))[0] or first_vals.get('antplus_device_type', (None,))[0]
    sn = first_vals.get('serial_number', (None,))[0]
    print(f"  Manufacturer: {mfg}, Product: {prod}, Type: {dev_type}, Serial: {sn}")
    print(f"  First TS: {first_ts}, Last TS: {last_ts}")
    
    # Check fields present across recs
    voltages = [r[1].get('battery_voltage', (None,))[0] for r in recs if r[1].get('battery_voltage', (None,))[0] is not None]
    battery_statuses = [r[1].get('battery_status', (None,))[0] for r in recs if r[1].get('battery_status', (None,))[0] is not None]
    battery_levels = [r[1].get('battery_level', (None,))[0] for r in recs if r[1].get('battery_level', (None,))[0] is not None]
    
    print(f"  Voltages ({len(voltages)} samples): min={min(voltages) if voltages else None}, max={max(voltages) if voltages else None}")
    print(f"  Battery statuses: {set(battery_statuses)}")
    if battery_levels:
        print(f"  Battery levels ({len(battery_levels)} samples): min={min(battery_levels)}, max={max(battery_levels)}")
    if voltages:
        print("  Sample voltages (first 5):", [(r[0], r[1].get('battery_voltage')[0]) for r in recs if r[1].get('battery_voltage', (None,))[0] is not None][:5])
