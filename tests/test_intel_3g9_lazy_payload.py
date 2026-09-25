import os
import sys
import pickle
import numpy as np
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from src.telemetry_processed_cache import LazySampleList
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin
from src.gui.qt.models import DataStream
from src.indicators.frame_data import prepare_overlay_frame_data
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value

class DummyTelemetry:
    def __init__(self):
        self.speed_samples = []
        self.track_samples = []
        self.gps_track = []
        self.fit_gps_track = []
        self.gpx_gps_track = []
        self.heading_samples = []
        self.slope_samples = []
        self.gyroscope_samples = []
        self.alt_samples = []
        self.iso_samples = []
        self.exposure_samples = []
        self.temperature_samples = []
        self.gpx_speed_samples = []
        self.gpx_hr_samples = []
        self.gpx_cad_samples = []
        self.gpx_power_samples = []
        self.gpx_atemp_samples = []
        self.gpx_heading_samples = []
        self.gpx_slope_samples = []
        self.fit_data = {}

        # Create large unmaterialized IMU LazySampleList objects (250k samples each)
        n = 250000
        ts = np.linspace(1700000000.0, 1700001000.0, n)
        vals = np.sin(np.linspace(0, 100, n))
        arr = np.column_stack([ts, vals])
        self.accel_x_samples = LazySampleList(arr.copy(), audit_label="test_accel_x")
        self.accel_y_samples = LazySampleList(arr.copy(), audit_label="test_accel_y")
        self.accel_z_samples = LazySampleList(arr.copy(), audit_label="test_accel_z")
        self.accel_magnitude_samples = LazySampleList(arr.copy(), audit_label="test_accel_mag")
        self.gyro_x_samples = LazySampleList(arr.copy(), audit_label="test_gyro_x")
        self.gyro_y_samples = LazySampleList(arr.copy(), audit_label="test_gyro_y")
        self.gyro_z_samples = LazySampleList(arr.copy(), audit_label="test_gyro_z")
        self.gyro_magnitude_samples = LazySampleList(arr.copy(), audit_label="test_gyro_mag")

class DummyIndicatorController(IndicatorMixin):
    def __init__(self, tm):
        self.telemetry = tm

@pytest.mark.intel
def test_discover_data_streams_lazy_safety():
    """Verify that _discover_data_streams does NOT materialize LazySampleList instances."""
    tm = DummyTelemetry()
    ctrl = DummyIndicatorController(tm)

    imu_attrs = [
        "accel_x_samples", "accel_y_samples", "accel_z_samples", "accel_magnitude_samples",
        "gyro_x_samples", "gyro_y_samples", "gyro_z_samples", "gyro_magnitude_samples"
    ]
    for attr in imu_attrs:
        assert getattr(tm, attr)._materialized is False

    streams = ctrl._discover_data_streams()
    assert len(streams) >= 8

    # Verify that all IMU streams remain completely unmaterialized
    for attr in imu_attrs:
        obj = getattr(tm, attr)
        assert obj._materialized is False, f"{attr} was materialized by _discover_data_streams!"

@pytest.mark.intel
def test_worker_init_args_compact_payload():
    """Verify that serialized worker init_args with unmaterialized streams is compact (< 35 MB)."""
    tm = DummyTelemetry()
    layout = {"indicators": {}, "custom_texts": []}
    field_samples = {
        "accel_x_samples": tm.accel_x_samples,
        "accel_y_samples": tm.accel_y_samples,
        "accel_z_samples": tm.accel_z_samples,
        "accel_magnitude_samples": tm.accel_magnitude_samples,
        "gyro_x_samples": tm.gyro_x_samples,
        "gyro_y_samples": tm.gyro_y_samples,
        "gyro_z_samples": tm.gyro_z_samples,
        "gyro_magnitude_samples": tm.gyro_magnitude_samples,
    }
    
    init_args = (
        3840, 2160, "arial.ttf", layout, field_samples, 10000.0,
        [], [], [], [], [], [], [], [], [], [],
        {}, [], datetime.now(timezone.utc), 2.0,
        [], [], [], 30.0, 1, 1131,
        [], 0, None, None, False, None, None
    )
    
    dumped = pickle.dumps(init_args, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = len(dumped) / (1024 * 1024)
    
    assert size_mb < 35.0, f"Worker init payload too large: {size_mb:.2f} MB"

@pytest.mark.intel
def test_lazy_telemetry_values_after_worker_startup():
    """Verify that unmaterialized LazySampleList correctly resolves sample values on demand."""
    n = 1000
    ts = np.linspace(1700000000.0, 1700001000.0, n)
    vals = np.cos(np.linspace(0, 10, n))
    arr = np.column_stack([ts, vals])
    lazy_list = LazySampleList(arr, audit_label="test_lazy")
    
    assert lazy_list._materialized is False
    assert len(lazy_list) == n
    
    sample_0 = lazy_list[0]
    assert lazy_list._materialized is True
    assert abs(sample_0[1] - vals[0]) < 1e-6
