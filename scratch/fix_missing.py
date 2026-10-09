with open('src/telemetry_native_gpmf.py', 'r') as f:
    text = f.read()

import re
old = '''def missing_native_channels(native_data: dict[str, Any] | None) -> tuple[str, ...]:
    return tuple(key for key, count in native_channel_counts(native_data).items() if count == 0)'''

new = '''def missing_native_channels(native_data: dict[str, Any] | None) -> tuple[str, ...]:
    if not native_data:
        return NATIVE_CHANNEL_KEYS
    present = set(native_data.get("present_channels", []))
    if not present:
        return tuple(key for key, count in native_channel_counts(native_data).items() if count == 0)
    
    # Map GPMF 4CC to our channel keys
    FOURCC_MAP = {
        "GPS5": ("gps_track", "speed_samples", "alt_samples", "track_samples"),
        "ACCL": ("accelerometer_samples",),
        "GYRO": ("gyroscope_samples",),
        "ISOS": ("iso_samples",),
        "SHUT": ("exposure_samples",),
        "CORI": (), # Camera orientation
        "IORI": (), # Image orientation
        "GRAV": (), # Gravity
        "WBAL": (), # White balance
    }
    
    expected_keys = set()
    for fourcc in present:
        if fourcc in FOURCC_MAP:
            expected_keys.update(FOURCC_MAP[fourcc])
            
    # Always expect temperature if any IMU is present
    if "ACCL" in present or "GYRO" in present:
        expected_keys.add("temperature_samples")
        
    return tuple(key for key, count in native_channel_counts(native_data).items() if count == 0 and key in expected_keys)'''

text = text.replace(old, new)
with open('src/telemetry_native_gpmf.py', 'w') as f:
    f.write(text)
