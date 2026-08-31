import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import fitparse

GARMIN_EPOCH = datetime(1989, 12, 31, 0, 0, 0, tzinfo=timezone.utc)

def parse_device_status_records(fitfile: fitparse.FitFile) -> list[dict[str, Any]]:
    """Parse message 104 (device_status / unknown_104) records."""
    dev_status_records: list[dict[str, Any]] = []
    
    # Try message names: unknown_104, device_status, battery_status
    status_msgs = list(fitfile.get_messages("unknown_104")) + list(fitfile.get_messages("device_status"))
    for msg in status_msgs:
        ts_val = None
        v_val = None
        pct_val = None
        temp_val = None
        
        for f in msg.fields:
            fname = str(f.name)
            fd = getattr(f, "field_def", None)
            def_num = getattr(fd, "def_num", None)
            
            # Timestamp (field 253)
            if fname in ("timestamp", "unknown_253") or def_num == 253:
                if isinstance(f.value, datetime):
                    ts_val = f.value
                elif isinstance(f.value, (int, float)):
                    ts_val = GARMIN_EPOCH + timedelta(seconds=f.value)
            
            # Voltage (field 0)
            elif fname in ("battery_voltage", "voltage", "unknown_0") or def_num == 0:
                if f.value is not None:
                    try:
                        num = float(f.value)
                        # If raw in millivolts (>100), scale to Volts
                        if num > 100.0:
                            num = num / 1000.0
                        v_val = num
                    except (ValueError, TypeError):
                        pass
            
            # Battery level / percent (field 2)
            elif fname in ("battery_level", "battery_percent", "battery_pct", "battery_soc", "battery", "unknown_2") or def_num == 2:
                if f.value is not None:
                    try:
                        pct_val = float(f.value)
                    except (ValueError, TypeError):
                        pass
            
            # Temperature (field 3)
            elif fname in ("temperature", "device_temperature", "unknown_3") or def_num == 3:
                if f.value is not None:
                    try:
                        temp_val = float(f.value)
                    except (ValueError, TypeError):
                        pass
        
        if ts_val is not None and (v_val is not None or pct_val is not None or temp_val is not None):
            dt = ts_val.replace(tzinfo=timezone.utc) if ts_val.tzinfo is None else ts_val.astimezone(timezone.utc)
            rec = {
                "timestamp": dt.replace(tzinfo=None),
            }
            if v_val is not None:
                rec["garmin_battery_voltage"] = v_val
            if pct_val is not None:
                rec["garmin_battery_percent"] = pct_val
            if temp_val is not None:
                rec["garmin_temperature"] = temp_val
            dev_status_records.append(rec)
            
    return dev_status_records

fit_path = Path(r'C:\_DEV\TeleM\Video\GX010114_116.fit')
fitfile = fitparse.FitFile(str(fit_path))
dev_records = parse_device_status_records(fitfile)
print(f"Extracted {len(dev_records)} device status records.")
print("Sample first 3:", dev_records[:3])
print("Sample last 3:", dev_records[-3:])
