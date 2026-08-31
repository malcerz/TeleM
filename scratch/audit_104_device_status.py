import fitparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

GARMIN_EPOCH = datetime(1989, 12, 31, 0, 0, 0, tzinfo=timezone.utc)

def garmin_ts_to_dt(ts_val):
    if isinstance(ts_val, datetime):
        return ts_val
    if isinstance(ts_val, (int, float)):
        return GARMIN_EPOCH + timedelta(seconds=ts_val)
    return None

fit_path = Path(r'C:\_DEV\TeleM\Video\GX010114_116.fit')
fitfile = fitparse.FitFile(str(fit_path))

records_104 = []
for msg in fitfile.get_messages('unknown_104'):
    vals = {f.name: (f.value, getattr(f, 'raw_value', None)) for f in msg.fields}
    ts_raw = vals.get('unknown_253', (None,))[0]
    dt = garmin_ts_to_dt(ts_raw)
    voltage_raw = vals.get('unknown_0', (None,))[0]
    voltage_v = voltage_raw / 1000.0 if voltage_raw is not None else None
    battery_pct = vals.get('unknown_2', (None,))[0]
    temp_c = vals.get('unknown_3', (None,))[0]
    field_4 = vals.get('unknown_4', (None,))[0]
    
    records_104.append({
        'dt_utc': dt,
        'ts_raw': ts_raw,
        'voltage_v': voltage_v,
        'battery_pct': battery_pct,
        'temp_c': temp_c,
        'field_4': field_4,
    })

print(f"Total unknown_104 (device_status) records: {len(records_104)}")
print(f"First record: {records_104[0]}")
print(f"Last record:  {records_104[-1]}")

voltages = [r['voltage_v'] for r in records_104 if r['voltage_v'] is not None]
pcts = [r['battery_pct'] for r in records_104 if r['battery_pct'] is not None]
temps = [r['temp_c'] for r in records_104 if r['temp_c'] is not None]

print(f"\nStats:")
print(f"  Voltage (V): count={len(voltages)}, min={min(voltages):.3f}, max={max(voltages):.3f}")
print(f"  Battery (%): count={len(pcts)}, min={min(pcts)}, max={max(pcts)}")
print(f"  Temp (°C):   count={len(temps)}, min={min(temps)}, max={max(temps)}")

print("\nFirst 10 records:")
for i, r in enumerate(records_104[:10]):
    print(f"  [{i:02d}] {r['dt_utc']} UTC | V={r['voltage_v']:.3f} V | Batt={r['battery_pct']} % | Temp={r['temp_c']} °C | f4={r['field_4']}")

print("\nRecords around 09:40 UTC (11:40 local):")
for r in records_104:
    if r['dt_utc'] and (r['dt_utc'].hour == 9 and 40 <= r['dt_utc'].minute <= 42):
        print(f"  {r['dt_utc']} UTC (local {r['dt_utc'].hour+2:02d}:{r['dt_utc'].minute:02d}:{r['dt_utc'].second:02d}) | V={r['voltage_v']:.3f} V | Batt={r['battery_pct']} % | Temp={r['temp_c']} °C")

print("\nRecords around 09:50 UTC (11:50 local):")
for r in records_104:
    if r['dt_utc'] and (r['dt_utc'].hour == 9 and 50 <= r['dt_utc'].minute <= 52):
        print(f"  {r['dt_utc']} UTC (local {r['dt_utc'].hour+2:02d}:{r['dt_utc'].minute:02d}:{r['dt_utc'].second:02d}) | V={r['voltage_v']:.3f} V | Batt={r['battery_pct']} % | Temp={r['temp_c']} °C")

print("\nRecords around 10:00 UTC (12:00 local):")
for r in records_104:
    if r['dt_utc'] and (r['dt_utc'].hour == 10 and 0 <= r['dt_utc'].minute <= 2):
        print(f"  {r['dt_utc']} UTC (local {r['dt_utc'].hour+2:02d}:{r['dt_utc'].minute:02d}:{r['dt_utc'].second:02d}) | V={r['voltage_v']:.3f} V | Batt={r['battery_pct']} % | Temp={r['temp_c']} °C")
