"""Tests for the TelemetryDataManager class."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from src.gui.telemetry_manager import (
    Sample,
    TelemetryDataManager,
    _align_offset_by_track,
    _compute_smart_time_offset,
)

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

    def test_get_samples_for_source_fit_has_no_implicit_gpmf_fallback(
        self, manager: TelemetryDataManager, samples: list[Sample]
    ) -> None:
        """An explicit FIT request must not silently return GPMF samples."""
        manager.load_gpmf_records([{"dummy": True}])
        spd, trk, alt = manager.get_samples_for_source("fit")
        assert spd == []
        assert trk == []
        assert alt == []

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
        """resolve_value('speed') should use linear interpolation (not the step mock)."""
        manager.load_gpmf_records([{"dummy": True}])
        val = manager.resolve_value("speed", dt, source="gpmf")
        # samples = [(dt, 50.0), (dt+1s, 55.0)]; target == dt → 50.0
        assert val == 50.0

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
        result = manager.resolve_samples("speed", "gpmf")
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


# ── SmartSync: GPS-track alignment ──────────────────────────────────────────


class TestResolveValueFieldAware:
    """resolve_value: liniowo dla prędkości/dystansu/wysokości, schodkowo dla reszty."""

    def _manager(self):
        from src.telemetry_extract import interpolate_value

        m = TelemetryDataManager()
        m._interpolate_fn = interpolate_value
        return m

    def test_enhanced_speed_linear(self):
        """Pole FIT enhanced_speed → interpolacja LINIOWA (płynny licznik)."""
        from datetime import datetime, timedelta

        m = self._manager()
        base = datetime(2026, 7, 29, 6, 30, 0)
        m.fit_data = {
            "enhanced_speed": [
                (base, 10.0),
                (base + timedelta(seconds=1), 20.0),
            ],
        }
        mid = base + timedelta(seconds=0.5)
        assert m.resolve_value("enhanced_speed", mid) == pytest.approx(15.0)

    def test_distance_linear(self):
        """Pole FIT distance → interpolacja LINIOWA (płynny dystans)."""
        from datetime import datetime, timedelta

        m = self._manager()
        base = datetime(2026, 7, 29, 6, 30, 0)
        m.fit_data = {
            "distance": [
                (base, 0.0),
                (base + timedelta(seconds=1), 100.0),
            ],
        }
        mid = base + timedelta(seconds=0.5)
        assert m.resolve_value("distance", mid) == pytest.approx(50.0)

    def test_hr_step(self):
        """Pole FIT heart_rate → interpolacja SCHODKOWA (co ~1 s)."""
        from datetime import datetime, timedelta

        m = self._manager()
        base = datetime(2026, 7, 29, 6, 30, 0)
        m.fit_data = {
            "heart_rate": [
                (base, 100.0),
                (base + timedelta(seconds=1), 120.0),
            ],
        }
        mid = base + timedelta(seconds=0.5)
        assert m.resolve_value("heart_rate", mid) == 100.0

    def test_hr_alias_step(self):
        """Alias "hr" → heart_rate, schodkowo."""
        from datetime import datetime, timedelta

        m = self._manager()
        base = datetime(2026, 7, 29, 6, 30, 0)
        m.fit_data = {
            "heart_rate": [
                (base, 100.0),
                (base + timedelta(seconds=1), 120.0),
            ],
        }
        mid = base + timedelta(seconds=0.5)
        assert m.resolve_value("hr", mid) == 100.0


class TestSmartTimeOffsetTrackAlignment:
    """Tests for GPS-track-based SmartSync offset alignment.

    The GoPro camera clock can drift by minutes/hours, so time-overlap
    matching alone is unreliable.  Matching GPS positions is ground truth.
    """

    # A small loop route around (54.0, 18.0)
    _ROUTE = [
        (54.000000, 18.000000),
        (54.000500, 18.000000),
        (54.001000, 18.000500),
        (54.000500, 18.001000),
        (54.000000, 18.001000),
        (54.000000, 18.000000),
        (54.000500, 18.000000),
        (54.001000, 18.000500),
        (54.000500, 18.001000),
        (54.000000, 18.001000),
        (54.000000, 18.000000),
    ]

    def _gpmf_track(self, start: datetime) -> list[tuple[datetime, float, float]]:
        """GPMF track with 10s spacing."""
        return [
            (start + timedelta(seconds=10 * i), lat, lon)
            for i, (lat, lon) in enumerate(self._ROUTE)
        ]

    def _fit_records(
        self, start: datetime
    ) -> list[dict]:
        """FIT records with the same route but 10s spacing + a clock offset."""
        return [
            {
                "timestamp": start + timedelta(seconds=10 * i),
                "lat": lat,
                "lon": lon,
            }
            for i, (lat, lon) in enumerate(self._ROUTE)
        ]

    def test_finds_true_clock_offset(self) -> None:
        """Video clock 1h behind FIT -> track alignment finds -3600s, not direct match."""
        video_start = datetime(2026, 7, 29, 6, 27, 54)
        fit_start = video_start + timedelta(hours=1)  # Garmin clock 1h ahead

        gpmf = self._gpmf_track(video_start)
        records = self._fit_records(fit_start)

        offset = _compute_smart_time_offset(
            records[0]["timestamp"],
            records[-1]["timestamp"],
            video_start,
            records=records,
            gpmf_track=gpmf,
        )
        assert offset == timedelta(hours=-1)

    def test_zero_offset_when_clocks_aligned(self) -> None:
        """Same ride, synced clocks -> offset 0."""
        video_start = datetime(2026, 7, 29, 6, 27, 54)
        gpmf = self._gpmf_track(video_start)
        records = self._fit_records(video_start)

        offset = _compute_smart_time_offset(
            records[0]["timestamp"],
            records[-1]["timestamp"],
            video_start,
            records=records,
            gpmf_track=gpmf,
        )
        assert offset == timedelta(0)

    def test_falls_back_to_direct_match_when_routes_differ(self) -> None:
        """Different ride (no position overlap) -> falls back to time-based match."""
        video_start = datetime(2026, 7, 29, 6, 27, 54)
        # FIT ride 10 km away (different route)
        gpmf = self._gpmf_track(video_start)
        records = [
            {
                "timestamp": video_start + timedelta(seconds=10 * i),
                "lat": lat + 0.1,
                "lon": lon + 0.1,
            }
            for i, (lat, lon) in enumerate(self._ROUTE)
        ]

        offset = _compute_smart_time_offset(
            records[0]["timestamp"],
            records[-1]["timestamp"],
            video_start,
            records=records,
            gpmf_track=gpmf,
        )
        # Direct time match wins (video start inside FIT range)
        assert offset == timedelta(0)

    def test_no_track_data_uses_time_match(self) -> None:
        """No GPS data -> plain time-based direct match."""
        video_start = datetime(2026, 7, 29, 6, 27, 54)
        records = self._fit_records(video_start)
        offset = _compute_smart_time_offset(
            records[0]["timestamp"],
            records[-1]["timestamp"],
            video_start,
            records=records,
            gpmf_track=[],
        )
        assert offset == timedelta(0)

    def test_align_offset_by_track_returns_none_without_data(self) -> None:
        """No positions -> None (caller falls back to time matching)."""
        assert _align_offset_by_track(None, None) is None
        assert _align_offset_by_track([], []) is None

    def test_align_offset_by_track_requires_absolute_overlap(self) -> None:
        """Track scoring does not invent a file-start offset without overlap."""
        video_start = datetime(2026, 7, 29, 6, 27, 54)
        fit_start = video_start - timedelta(hours=1)  # Garmin clock 1h behind

        gpmf = self._gpmf_track(video_start)
        records = self._fit_records(fit_start)

        offset = _align_offset_by_track(records, gpmf)
        assert offset is None

    def test_absolute_trajectory_refinement_preserves_sign_convention(self) -> None:
        """FIT shifted by +1.2 s requires offset -1.2 s to align it."""
        start = datetime(2026, 7, 29, 6, 27, 54)
        gpmf = self._gpmf_track(start)
        records = [
            {"timestamp": dt + timedelta(seconds=1.2), "lat": lat, "lon": lon}
            for dt, lat, lon in gpmf
        ]

        offset = _compute_smart_time_offset(
            records[0]["timestamp"], records[-1]["timestamp"], start,
            records=records, gpmf_track=gpmf,
        )
        assert offset.total_seconds() == pytest.approx(-1.2, abs=0.2)


    def test_absolute_anchor_wins_over_later_repeated_segment(self) -> None:
        """A later spatially identical segment must not replace the time anchor."""
        start = datetime(2026, 7, 29, 6, 0, 0)
        route = [(54.0, 18.0), (54.001, 18.0), (54.002, 18.001)]
        gpmf = [(start + timedelta(seconds=i), *pos) for i, pos in enumerate(route)]
        records = [
            {"timestamp": start + timedelta(seconds=i), "lat": lat, "lon": lon}
            for i, (lat, lon) in enumerate(route)
        ]
        records += [
            {"timestamp": start + timedelta(seconds=600 + i), "lat": lat, "lon": lon}
            for i, (lat, lon) in enumerate(route)
        ]
        assert _compute_smart_time_offset(
            records[0]["timestamp"], records[-1]["timestamp"], start,
            records=records, gpmf_track=gpmf,
        ) == timedelta(0)

    def test_short_gpmf_long_fit_uses_temporal_overlap(self) -> None:
        """A short clip is aligned without requiring FIT and GPMF to have equal length."""
        start = datetime(2026, 7, 29, 6, 0, 0)
        route = [(54.0 + i * 0.001, 18.0 + i * 0.001) for i in range(12)]
        gpmf = [(start + timedelta(seconds=i), *pos) for i, pos in enumerate(route)]
        records = [
            {"timestamp": start + timedelta(seconds=i), "lat": lat, "lon": lon}
            for i, (lat, lon) in enumerate(route)
        ]
        records.extend(
            {"timestamp": start + timedelta(seconds=60 + i), "lat": 55.0, "lon": 19.0}
            for i in range(600)
        )
        assert _compute_smart_time_offset(
            records[0]["timestamp"], records[-1]["timestamp"], start,
            records=records, gpmf_track=gpmf,
        ) == timedelta(0)


@pytest.mark.skipif(
    not (Path("Video/GX020079.json").exists() and Path("Video/Morning_Ride.fit").exists()),
    reason="real SmartSync fixtures not present",
)
def test_real_gx020079_morning_ride_prefers_absolute_anchor() -> None:
    """Regression: the real case must not select the old -27:45 segment."""
    import json

    from src.telemetry_extract import extract_gps_track, find_gps_anchor
    from telemetry_fit import parse_fit

    with open("Video/GX020079.json", encoding="utf-8") as handle:
        records = json.load(handle)
    gpmf_track = extract_gps_track(records)
    fit_records = parse_fit("Video/Morning_Ride.fit")
    offset = _compute_smart_time_offset(
        fit_records[0]["timestamp"], fit_records[-1]["timestamp"],
        find_gps_anchor(records), fit_records, gpmf_track,
    )
    assert offset.total_seconds() == pytest.approx(-1.0, abs=2.0)
