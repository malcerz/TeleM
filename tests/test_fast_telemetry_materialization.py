"""Small, focused unit tests for fast telemetry materialization, array-backed streams, and parity."""

from datetime import datetime, timezone
import numpy as np
import pytest

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import (
    LazySampleList,
    write_processed_cache,
    read_processed_cache,
    apply_processed_cache,
    read_processed_cache_arrays,
    apply_processed_cache_arrays,
    processed_cache_path,
)


def test_lazy_sample_list_semantics():
    dt = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)
    arr = np.array([[dt.timestamp(), 1.0, 2.0, 3.0]], dtype=np.float64)
    lazy = LazySampleList(arr, is_vector=True, tz_aware=True)

    # 1. len and bool are O(1) without materialization
    assert len(lazy) == 1
    assert bool(lazy) is True
    assert not lazy._materialized

    # 2. Accessing item materializes on demand
    item0 = lazy[0]
    assert lazy._materialized
    assert item0[0] == dt
    assert item0[1] == (1.0, 2.0, 3.0)

    # 3. Equality with normal Python list of tuples
    assert lazy == [(dt, (1.0, 2.0, 3.0))]


def test_lazy_sample_list_bool_truthiness():
    # 1. Non-empty array: bool is True, NO materialization
    dt = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)
    arr = np.array([[dt.timestamp(), 1.0, 2.0, 3.0]], dtype=np.float64)
    lazy_non_empty = LazySampleList(arr, is_vector=True, tz_aware=True)
    assert not lazy_non_empty._materialized
    assert bool(lazy_non_empty) is True
    assert not lazy_non_empty._materialized  # Must remain unmaterialized!

    # 2. Empty array: bool is False, NO materialization
    empty_arr = np.zeros((0, 4), dtype=np.float64)
    lazy_empty = LazySampleList(empty_arr, is_vector=True, tz_aware=True)
    assert not lazy_empty._materialized
    assert bool(lazy_empty) is False
    assert not lazy_empty._materialized

    # 3. None array: bool is False, NO materialization
    lazy_none = LazySampleList(None, is_vector=True, tz_aware=True)
    assert not lazy_none._materialized
    assert bool(lazy_none) is False
    assert not lazy_none._materialized

    # 4. Materialized list: bool works without AttributeError: 'super' object has no attribute '__bool__'
    lazy_non_empty._materialize()
    assert lazy_non_empty._materialized is True
    assert bool(lazy_non_empty) is True

    # 5. Materialized empty list
    lazy_empty._materialize()
    assert lazy_empty._materialized is True
    assert bool(lazy_empty) is False


def test_lazy_sample_list_mutations():
    dt = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)
    arr = np.array([[dt.timestamp(), 1.0, 2.0, 3.0]], dtype=np.float64)
    lazy = LazySampleList(arr, is_vector=True, tz_aware=True)

    # Mutator methods materialize safely and retain all items
    dt2 = datetime(2026, 8, 14, 11, 18, 4, tzinfo=timezone.utc)
    lazy.extend([(dt2, (4.0, 5.0, 6.0))])
    assert lazy._materialized is True
    assert len(lazy) == 2
    assert bool(lazy) is True
    assert lazy[0][0] == dt
    assert lazy[1][0] == dt2


def test_vectorized_accel_parity():
    dt0 = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)
    ts0 = dt0.timestamp()
    N = 1000
    times = ts0 + np.arange(N) * 0.005
    x = np.linspace(-2.0, 2.0, N)
    y = np.linspace(-1.0, 1.0, N)
    z = np.linspace(-9.8, -9.0, N)
    arr = np.column_stack([times, x, y, z])

    tm = TelemetryDataManager()
    tm._set_vector_series_from_array(arr, "accel", tz_aware=True)

    # Magnitude calculation parity
    expected_mag = np.sqrt(x * x + y * y + z * z)
    assert np.allclose(tm.accel_magnitude_array[:, 1], expected_mag, rtol=1e-12, atol=1e-12)

    # Parity when materialized as sample tuples
    mag_samples = tm.accel_magnitude_samples
    assert len(mag_samples) == N
    assert mag_samples[0][0] == dt0
    assert pytest.approx(mag_samples[0][1]) == expected_mag[0]
    assert pytest.approx(mag_samples[-1][1]) == expected_mag[-1]


def test_vectorized_gyro_parity():
    dt0 = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)
    ts0 = dt0.timestamp()
    N = 1000
    times = ts0 + np.arange(N) * 0.005
    gx = np.sin(np.linspace(0, 10, N))
    gy = np.cos(np.linspace(0, 10, N))
    gz = np.linspace(-0.5, 0.5, N)
    arr = np.column_stack([times, gx, gy, gz])

    tm = TelemetryDataManager()
    tm._set_vector_series_from_array(arr, "gyro", tz_aware=True)

    expected_mag = np.sqrt(gx * gx + gy * gy + gz * gz)
    assert np.allclose(tm.gyro_magnitude_array[:, 1], expected_mag, rtol=1e-12, atol=1e-12)

    mag_samples = tm.gyro_magnitude_samples
    assert len(mag_samples) == N
    assert mag_samples[0][0] == dt0
    assert pytest.approx(mag_samples[0][1]) == expected_mag[0]


def test_timestamp_fast_path_parity(tmp_path):
    source = tmp_path / "test_clip.MP4"
    source.write_bytes(b"dummy_video_source")

    tm = TelemetryDataManager()
    dt = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)
    tm.start_dt_utc = dt
    tm.speed_samples = [(dt, 25.5)]
    tm.gps_track = [(dt, 54.39, 18.57)]
    tm.accelerometer_samples = [(dt, (0.1, 0.2, 9.8))]
    tm.gyroscope_samples = [(dt, (0.01, 0.02, 0.03))]

    write_processed_cache(source, tm)

    # Read using fast array reader
    arrays, meta = read_processed_cache_arrays(source)
    assert arrays is not None
    assert meta["start_dt_utc"] == dt.isoformat()

    restored = TelemetryDataManager()
    apply_processed_cache_arrays(restored, arrays, meta)

    assert restored.start_dt_utc == dt
    assert restored.speed_samples == [(dt, 25.5)]
    assert restored.gps_track == [(dt, 54.39, 18.57)]
    assert restored.accelerometer_samples == [(dt, (0.1, 0.2, 9.8))]
    assert restored.gyroscope_samples == [(dt, (0.01, 0.02, 0.03))]


def test_processed_cache_fast_apply(tmp_path):
    source = tmp_path / "test_fast_apply.MP4"
    source.write_bytes(b"dummy_video_source")

    tm = TelemetryDataManager()
    dt = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)
    tm.start_dt_utc = dt
    tm.speed_samples = [(dt, 15.0)]
    tm.accelerometer_samples = [(dt, (1.0, 2.0, 3.0))]
    tm.gyroscope_samples = [(dt, (4.0, 5.0, 6.0))]

    write_processed_cache(source, tm)

    fields = read_processed_cache(source)
    assert fields is not None

    restored = TelemetryDataManager()
    apply_processed_cache(restored, fields)

    assert restored.start_dt_utc == dt
    assert restored.speed_samples == [(dt, 15.0)]
    assert restored.accelerometer_samples == [(dt, (1.0, 2.0, 3.0))]
    assert restored.gyroscope_samples == [(dt, (4.0, 5.0, 6.0))]
    assert len(restored.accel_magnitude_samples) == 1
    assert pytest.approx(restored.accel_magnitude_samples[0][1]) == (1.0 + 4.0 + 9.0) ** 0.5
