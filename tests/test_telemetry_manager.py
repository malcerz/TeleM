"""Tests for the TelemetryDataManager class."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from src.gui.telemetry_manager import Sample, TelemetryDataManager

# ── Mock function factories ─────────────────────────────────────────────────


def _make_extract_fn(
    samples: list[Sample],
) -> Any:
    """Return a mock extract function that returns predefined samples."""

    def _extract(records: list[dict]) -> list[Sample]:
        return samples

    return _extract


def _make_smooth_fn() -> Any:
    """Return a mock smooth function that passes through unchanged."""

    def _smooth(
        samples: list[Sample], method: str, window: int
    ) -> list[Sample]:
        return samples

    return _smooth


def _make_interpolate_fn(expected: Optional[float] = 42.0) -> Any:
    """Return a mock interpolate function."""

    def _interpolate(
        samples: list[Sample], target_dt: datetime
    ) -> Optional[float]:
        return expected

    return _interpolate


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def dt() -> datetime:
    return datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def samples(dt: datetime) -> list[Sample]:
    return [(dt, 50.0), (datetime(2024, 6, 15, 10, 0, 1), 55.0)]


@pytest.fixture
def manager(samples: list[Sample]) -> TelemetryDataManager:
    return TelemetryDataManager(
        extract_speed_fn=_make_extract_fn(samples),
        extract_altitude_fn=_make_extract_fn(samples),
        extract_track_fn=_make_extract_fn(samples),
        extract_iso_fn=_make_extract_fn([]),
        extract_exposure_fn=_make_extract_fn([]),
        extract_temperature_fn=_make_extract_fn([]),
        smooth_fn=_make_smooth_fn(),
        interpolate_fn=_make_interpolate_fn(42.0),
    )


# ── Tests ───────────────────────────────────────────────────────────────────


class TestTelemetryDataManager:
    """Tests for TelemetryDataManager."""

    def test_init(self, manager: TelemetryDataManager) -> None:
        """Manager should start with empty data."""
        assert manager.records == []
        assert manager.speed_samples == []
        assert manager.gpx_speed_samples == []
        assert manager.fit_data == {}
        assert manager.start_dt_utc is None

    def test_load_gpmf_records(self, manager: TelemetryDataManager) -> None:
        """load_gpmf_records() should populate samples from extract functions."""
        records = [{"some": "data"}]
        manager.load_gpmf_records(records)
        assert manager.records == records
        assert len(manager.speed_samples) == 2
        assert manager.speed_samples[0][1] == 50.0

    def test_get_samples_for_source_gpmf(
        self, manager: TelemetryDataManager, samples: list[Sample]
    ) -> None:
        """get_samples_for_source('gpmf') should return GPMF samples."""
        manager.load_gpmf_records([{"dummy": True}])
        spd, trk, alt = manager.get_samples_for_source("gpmf")
        assert spd == samples
        assert trk == samples
        assert alt == samples

    def test_get_samples_for_source_fit_fallback(
        self, manager: TelemetryDataManager, samples: list[Sample]
    ) -> None:
        """get_samples_for_source('fit') should fall back to GPMF when no FIT data."""
        manager.load_gpmf_records([{"dummy": True}])
        spd, trk, alt = manager.get_samples_for_source("fit")
        assert spd == samples  # falls back to GPMF

    def test_get_samples_for_source_gpx(
        self, manager: TelemetryDataManager, samples: list[Sample]
    ) -> None:
        """get_samples_for_source('gpx') should return GPX data when available."""
        manager.load_gpmf_records([{"dummy": True}])
        manager.gpx_speed_samples = [(samples[0][0], 60.0)]
        spd, _, _ = manager.get_samples_for_source("gpx")
        assert spd[0][1] == 60.0

    def test_resolve_value(
        self, manager: TelemetryDataManager, dt: datetime
    ) -> None:
        """resolve_value() should return interpolated value."""
        manager.load_gpmf_records([{"dummy": True}])
        val = manager.resolve_value("speed", dt)
        assert val == 42.0

    def test_resolve_value_no_data(
        self, manager: TelemetryDataManager, dt: datetime
    ) -> None:
        """resolve_value() should return None when no data."""
        val = manager.resolve_value("nonexistent", dt)
        assert val is None

    def test_resolve_samples(
        self, manager: TelemetryDataManager, samples: list[Sample]
    ) -> None:
        """resolve_samples() should return raw sample list."""
        manager.load_gpmf_records([{"dummy": True}])
        result = manager.resolve_samples("speed")
        assert result == samples

    def test_clear_source(self, manager: TelemetryDataManager) -> None:
        """clear_source() should clear the specified source."""
        manager.gpx_speed_samples = [(datetime.now(), 10.0)]
        manager.gpx_path = "/some/path.gpx"
        manager.clear_source("gpx")
        assert manager.gpx_speed_samples == []
        assert manager.gpx_path is None

    def test_clear_all(self, manager: TelemetryDataManager) -> None:
        """clear_all() should wipe all data."""
        manager.load_gpmf_records([{"dummy": True}])
        manager.fit_data["speed"] = [(datetime.now(), 10.0)]
        manager.clear_all()
        assert manager.records == []
        assert manager.speed_samples == []
        assert manager.fit_data == {}

    def test_rotation_no_data(self, manager: TelemetryDataManager) -> None:
        """get_rotation_from_metadata() should return 0 when no rotation function."""
        assert manager.get_rotation_from_metadata() == 0

    def test_container_rotation_no_data(
        self, manager: TelemetryDataManager
    ) -> None:
        """get_container_rotation() should return 0 when no function or path."""
        assert manager.get_container_rotation() == 0

    def test_set_callbacks(self, manager: TelemetryDataManager) -> None:
        """set_callbacks() should store callbacks."""
        calls: list[str] = []

        def on_loaded() -> None:
            calls.append("loaded")

        def on_error(msg: str) -> None:
            calls.append(f"error:{msg}")

        manager.set_callbacks(on_loaded=on_loaded, on_error=on_error)
        assert manager._on_telemetry_loaded is not None
        assert manager._on_error is not None

    def test_generate_meta_json_no_paths(
        self, manager: TelemetryDataManager
    ) -> None:
        """generate_meta_json() should return None when no video paths."""
        result = manager.generate_meta_json(video_paths=[])
        assert result is None

    def test_generate_meta_json_no_functions(
        self, manager: TelemetryDataManager
    ) -> None:
        """generate_meta_json() should return None when no meta functions injected."""
        result = manager.generate_meta_json(
            video_paths=None, exiftool_path="exiftool", silent=True
        )
        assert result is None
