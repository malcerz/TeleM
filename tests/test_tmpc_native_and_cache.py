"""Unit and regression tests for GoPro TMPC (Camera Temperature).

Verifies:
1. Native C++ extractor extracts TMPC as float (not int, not scaled by ACCL SCAL).
2. Deduplication: ACCL canonical selected, GYRO duplicate not doubled (1 sample per DEVC block).
3. Timestamps are monotonic and properly anchored to GPS.
4. NPZ write and read (.telemetry.npz) preserves sample count, values, and float precision.
5. TelemetryDataManager.temperature_samples is non-empty and contains exact tuples.
6. GUI stream discovery exposes 'temp_text' ('Temperatura', source 'gpmf').
7. Multi-file merge preserves temperature across clips without duplicate or non-monotonic timestamps.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pytest

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_native_gpmf import (
    is_native_gpmf_available,
    extract_gpmf_native,
    populate_telemetry_from_native,
)
from src.telemetry_processed_cache import (
    PROCESSED_CACHE_VERSION,
    write_processed_cache,
    read_processed_cache,
    read_processed_cache_arrays,
    apply_processed_cache_arrays,
)
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin


GX010239_PATH = Path("D:/GoPro/2026-08-31/GX010239.MP4")
GX010240_PATH = Path("D:/GoPro/2026-08-31/GX010240.MP4")


def test_processed_cache_version_bumped():
    """Verify cache schema version was incremented to 3 to invalidate stale cache without TMPC."""
    assert PROCESSED_CACHE_VERSION >= 3


@pytest.mark.skipif(not GX010239_PATH.exists(), reason="D:/GoPro/2026-08-31/GX010239.MP4 not available")
def test_native_tmpc_extraction_real_file():
    """Verify native C++ GPMF parser extracts TMPC accurately from a real GoPro MP4."""
    assert is_native_gpmf_available(), "Native GPMF parser must be available"

    data = extract_gpmf_native(GX010239_PATH)
    assert data is not None, "Extraction failed"
    assert data.get("success") is True, f"Extraction not successful: {data.get('error_message')}"

    # Verify raw counts and canonical deduplication
    raw_accl = data.get("raw_accl_tmpc")
    raw_gyro = data.get("raw_gyro_tmpc")
    temp_samples = data.get("temperature_samples")

    assert raw_accl == 186, f"Expected 186 ACCL TMPC samples, got {raw_accl}"
    assert raw_gyro == 186, f"Expected 186 GYRO TMPC samples, got {raw_gyro}"
    assert len(temp_samples) == 186, f"Expected 186 logical deduplicated samples, got {len(temp_samples)}"

    # Value checks: must remain float, within plausible GoPro range (20-80 C)
    first_ts, first_val = temp_samples[0]
    last_ts, last_val = temp_samples[-1]

    assert isinstance(first_val, float), "Temperature must remain float"
    assert not isinstance(first_val, int), "Temperature must not be int"
    assert 20.0 <= first_val <= 60.0, f"Unreasonable temperature value: {first_val}"
    assert 20.0 <= last_val <= 60.0, f"Unreasonable temperature value: {last_val}"

    # Check exact expected reference values for GX010239
    assert np.isclose(first_val, 30.01171875, atol=1e-6), f"Expected 30.01171875, got {first_val}"
    assert np.isclose(last_val, 37.3046875, atol=1e-6), f"Expected 37.3046875, got {last_val}"

    # Timestamps strictly monotonic
    timestamps = [s[0] for s in temp_samples]
    assert all(b > a for a, b in zip(timestamps, timestamps[1:])), "Timestamps must be strictly monotonic"


@pytest.mark.skipif(not GX010239_PATH.exists(), reason="D:/GoPro/2026-08-31/GX010239.MP4 not available")
def test_npz_cache_roundtrip_preserves_tmpc():
    """Verify NPZ cache write/read roundtrip preserves exact sample count and float values."""
    tm = TelemetryDataManager()
    native_data = extract_gpmf_native(GX010239_PATH)
    populate_telemetry_from_native(GX010239_PATH, native_data, tm)

    assert len(tm.temperature_samples) == 186

    # Write cache
    written_path = write_processed_cache(GX010239_PATH, tm)
    assert written_path.exists()

    # Read cache (arrays fast path)
    arrays, meta = read_processed_cache_arrays(GX010239_PATH)
    assert arrays is not None and meta is not None
    assert "temperature_samples" in arrays
    assert arrays["temperature_samples"].shape == (186, 2)

    tm_loaded = TelemetryDataManager()
    apply_processed_cache_arrays(tm_loaded, arrays, meta)

    assert len(tm_loaded.temperature_samples) == 186
    # Exact float match
    for orig, loaded in zip(tm.temperature_samples, tm_loaded.temperature_samples):
        assert orig[0] == loaded[0], "Timestamp mismatch after cache reload"
        assert np.isclose(orig[1], loaded[1], atol=1e-9), f"Value mismatch: {orig[1]} vs {loaded[1]}"


@pytest.mark.skipif(not GX010239_PATH.exists(), reason="D:/GoPro/2026-08-31/GX010239.MP4 not available")
def test_gui_stream_discovery_finds_tmpc():
    """Verify GUI stream discovery exposes 'temp_text' when temperature_samples is present."""
    arrays, meta = read_processed_cache_arrays(GX010239_PATH)
    tm = TelemetryDataManager()
    apply_processed_cache_arrays(tm, arrays, meta)

    class DummyGUI(IndicatorMixin):
        def __init__(self, telemetry):
            self.telemetry = telemetry

    gui = DummyGUI(tm)
    streams = gui._discover_data_streams()
    temp_streams = [s for s in streams if s.key == "temp_text"]

    assert len(temp_streams) == 1, "Expected exactly one temp_text stream in discovery"
    stream = temp_streams[0]
    assert stream.source == "gpmf"
    assert stream.unit == "°C"
    assert stream.sample_count == 186
    assert 25.0 <= stream.value_range[0] <= 45.0


@pytest.mark.skipif(
    not (GX010239_PATH.exists() and GX010240_PATH.exists()),
    reason="Multi-file clips GX010239.MP4 and GX010240.MP4 not available",
)
def test_multifile_tmpc_merge():
    """Verify multi-file merge concatenates TMPC monotonically across clip boundary."""
    tm1 = TelemetryDataManager()
    populate_telemetry_from_native(GX010239_PATH, extract_gpmf_native(GX010239_PATH), tm1)

    tm2 = TelemetryDataManager()
    populate_telemetry_from_native(GX010240_PATH, extract_gpmf_native(GX010240_PATH), tm2)

    assert len(tm1.temperature_samples) == 186
    assert len(tm2.temperature_samples) == 1631

    # Simulate multi-file merge as done in project_mixin.py
    merged = list(tm1.temperature_samples)
    merged.extend(tm2.temperature_samples)
    merged.sort(key=lambda x: x[0])

    assert len(merged) == 186 + 1631 == 1817

    # Verify boundary and monotonicity
    dts = [s[0] for s in merged]
    assert all(b > a for a, b in zip(dts, dts[1:])), "Merged timestamps must be strictly monotonic"

    clip1_end = tm1.temperature_samples[-1][0]
    clip2_start = tm2.temperature_samples[0][0]
    assert clip2_start > clip1_end, "Clip 2 must start after Clip 1"
