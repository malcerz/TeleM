from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.telemetry_extract import (
    interpolate_exposure,
    interpolate_iso,
    interpolate_temperature,
    interpolate_value,
)


BASE = datetime(2026, 8, 18, 4, 46, 40, tzinfo=timezone.utc)


def samples():
    return [
        (BASE, 100.0),
        (BASE + timedelta(seconds=1), 200.0),
        (BASE + timedelta(seconds=2), 300.0),
    ]


def test_step_boundaries_previous_or_equal():
    s = samples()
    assert interpolate_value(s, BASE - timedelta(microseconds=1)) is None
    assert interpolate_value(s, BASE) == 100.0
    assert interpolate_value(s, BASE + timedelta(milliseconds=500)) == 100.0
    assert interpolate_value(s, BASE + timedelta(seconds=1)) == 200.0
    assert interpolate_value(s, BASE + timedelta(seconds=1, microseconds=-1)) == 100.0
    assert interpolate_value(s, BASE + timedelta(seconds=1, microseconds=1)) == 200.0
    assert interpolate_value(s, BASE + timedelta(seconds=2)) == 300.0
    assert interpolate_value(s, BASE + timedelta(seconds=3)) == 300.0


def test_step_exact_zero_and_duplicate_timestamp_policy():
    s = [(BASE, 5.0), (BASE + timedelta(seconds=1), 0.0), (BASE + timedelta(seconds=2), 7.0)]
    assert interpolate_value(s, BASE + timedelta(seconds=1)) == 0.0
    assert interpolate_value(s, BASE + timedelta(seconds=1, microseconds=1)) == 0.0

    duplicate = [(BASE, 1.0), (BASE, 2.0), (BASE + timedelta(seconds=1), 3.0)]
    assert interpolate_value(duplicate, BASE) == 2.0


def test_all_gpmf_step_helpers_use_same_boundary_contract():
    s = [(BASE, 10), (BASE + timedelta(seconds=1), 20)]
    for helper in (interpolate_iso, interpolate_exposure, interpolate_temperature):
        assert helper(s, BASE - timedelta(microseconds=1)) is None
        assert helper(s, BASE) == 10
        assert helper(s, BASE + timedelta(seconds=1)) == 20
