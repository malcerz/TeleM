from datetime import datetime, timezone
from math import sqrt

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    extract_accelerometer_samples,
    extract_gyroscope_samples,
    interpolate_value,
)


def _records():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{
        "Doc1:GPSDateTime": "2026:01:01 00:00:00.000",
        "Doc1:ACCL": [[10.0, 20.0, 30.0], [11.0, 21.0, 31.0]],
        "Doc1:ACCL_STMP": 1000,
        "Doc1:ACCL_TSMP": 1,
        "Doc2:ACCL": [[40.0, 50.0, 60.0]],
        "Doc2:ACCL_STMP": 1002,
        "Doc2:ACCL_TSMP": 2,
        "Doc1:GYRO": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        "Doc1:GYRO_STMP": 1000,
        "Doc1:GYRO_TSMP": 1,
        "Doc2:GYRO": [[7.0, 8.0, 9.0]],
        "Doc2:GYRO_STMP": 1002,
        "Doc2:GYRO_TSMP": 2,
    }]


def test_imu_zxy_mapping_and_short_final_block():
    accel = extract_accelerometer_samples(_records())
    gyro = extract_gyroscope_samples(_records())
    assert len(accel) == len(gyro) == 3
    assert accel[0][1] == (20.0, 30.0, 10.0)
    assert gyro[0][1] == (2.0, 3.0, 1.0)
    assert all(b[0] > a[0] for a, b in zip(accel, accel[1:]))


def test_imu_manager_magnitude_and_source_contract():
    manager = TelemetryDataManager(
        extract_accelerometer_fn=extract_accelerometer_samples,
        extract_gyroscope_fn=extract_gyroscope_samples,
        interpolate_fn=interpolate_value,
    )
    manager.load_gpmf_records(_records())
    dt = manager.accel_x_samples[0][0]
    assert manager.resolve_value("accel_x", dt, source="gpmf") == 20.0
    assert manager.resolve_value("accel_magnitude", dt, source="gpmf") == sqrt(20.0**2 + 30.0**2 + 10.0**2)
    assert manager.resolve_value("accel_x", dt, source="fit") is None
    assert len(manager.accel_x_samples) == len(manager.gyro_x_samples) == 3
