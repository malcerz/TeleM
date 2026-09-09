"""Opt-in integration proof for the user's real merged 12.fit binaries.

Run with TELEM_REAL_12_FIT and, optionally, TELEM_REAL_12_FIXED_FIT.  Keeping
the external paths in environment variables avoids turning a developer-local
drive layout into a normal test-suite dependency.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import fitparse
import pytest

from telemetry_fit import parse_fit, sync_fit_to_video
from src.gui.qt._mixins.preview_mixin import PreviewMixin
from src.gui.qt.tabs.render_tab import RenderTab
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_extract import interpolate_distance
from src.telemetry_precompute import _vectorize_linear_distance
from src.telemetry_resolver import (
    build_activity_range_cache,
    resolve_distance_samples,
)


SESSION_TOTAL_M = 14148.73
LAP_TOTALS_M = (6371.32, 7777.41)
RESET_FROM = (datetime(2026, 9, 1, 13, 28, 3), 6371.32)
RESET_TO = (datetime(2026, 9, 1, 13, 30, 24), 0.0)


def _required_real_path(env_name: str) -> Path:
    raw = os.environ.get(env_name)
    if not raw:
        pytest.skip(f"{env_name} is required for the opt-in real FIT test")
    path = Path(raw)
    if not path.is_file():
        pytest.fail(f"real FIT file does not exist: {path}")
    return path


@pytest.fixture(scope="module")
def real_12():
    path = _required_real_path("TELEM_REAL_12_FIT")
    records = parse_fit(path)
    assert records is not None
    dataset = sync_fit_to_video(records, records[0]["timestamp"])
    return path, records, dataset


def test_real_binary_session_laps_records_and_reset(real_12):
    path, records, _dataset = real_12
    fit = fitparse.FitFile(str(path), check_crc=False)
    sessions = [
        {field.name: field.value for field in message.fields}
        for message in fit.get_messages("session")
    ]
    laps = [
        {field.name: field.value for field in message.fields}
        for message in fit.get_messages("lap")
    ]
    raw_distance = [
        (record["timestamp"], float(record["distance"]))
        for record in records
        if record.get("distance") is not None
    ]
    drops = [
        (raw_distance[index - 1], raw_distance[index])
        for index in range(1, len(raw_distance))
        if raw_distance[index][1] < raw_distance[index - 1][1]
    ]

    assert len(sessions) == 1
    assert len(laps) == 2
    assert len(raw_distance) == 2775
    assert sessions[0]["total_distance"] == pytest.approx(SESSION_TOTAL_M)
    assert tuple(lap["total_distance"] for lap in laps) == pytest.approx(
        LAP_TOTALS_M
    )
    assert drops == [(RESET_FROM, RESET_TO)]


def test_real_production_parser_dataset_normalization_and_resolver(real_12):
    _path, _records, dataset = real_12
    distance = resolve_distance_samples("fit", fit_data=dataset)
    summary = dataset.distance_normalization

    assert distance is dataset["distance"]
    assert summary.segments == 2
    assert summary.resets == 1
    assert summary.segment_ends == pytest.approx(LAP_TOTALS_M)
    assert summary.normalized_final == pytest.approx(SESSION_TOTAL_M)
    assert summary.session_total == pytest.approx(SESSION_TOTAL_M)
    assert summary.match is True
    assert distance.segment_start_indices == (1252,)
    assert all(right[1] >= left[1] for left, right in zip(distance, distance[1:]))


def test_real_gap_holds_last_value_scalar_and_vectorized(real_12):
    np = pytest.importorskip("numpy")
    _path, _records, dataset = real_12
    distance = resolve_distance_samples("fit", fit_data=dataset)
    boundary = distance.segment_start_indices[0]
    segment_end = distance[boundary - 1]
    segment_start = distance[boundary]
    midpoint = segment_end[0] + (segment_start[0] - segment_end[0]) / 2
    probes = [
        segment_end[0] - timedelta(seconds=1),
        midpoint,
        segment_start[0] - timedelta(microseconds=1),
        segment_start[0],
        segment_start[0] + timedelta(seconds=5),
    ]
    scalar = [interpolate_distance(distance, timestamp) for timestamp in probes]
    ref_dt = distance[0][0]
    target_ts = np.array(
        [(timestamp - ref_dt).total_seconds() for timestamp in probes]
    )
    vectorized = _vectorize_linear_distance(distance, probes, target_ts, ref_dt)

    assert segment_end == (RESET_FROM[0], RESET_FROM[1])
    assert segment_start == (RESET_TO[0], RESET_FROM[1])
    assert scalar == pytest.approx([RESET_FROM[1]] * len(probes))
    assert vectorized == pytest.approx(scalar)
    assert interpolate_distance(dataset["track"], midpoint) != pytest.approx(
        RESET_FROM[1]
    )
    assert interpolate_distance(
        distance, segment_start[0] + timedelta(seconds=21)
    ) == pytest.approx(6372.49)


def _telemetry(dataset):
    return SimpleNamespace(
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        gpx_speed_samples=[],
        gpx_track_samples=[],
        gpx_alt_samples=[],
        gpx_power_samples=[],
        gpx_atemp_samples=[],
        gpx_hr_samples=[],
        gpx_cad_samples=[],
        iso_samples=[],
        exposure_samples=[],
        temperature_samples=[],
        fit_data=dataset,
    )


def _frame(layout, dataset, cache, target_dt):
    distance = resolve_distance_samples("fit", fit_data=dataset)
    return prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2.0,
        start_dt_utc=distance[0][0],
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        fit_data=dataset,
        resolve_cache_value=lambda field, source, when, indicator_key=None: (
            interpolate_distance(distance, when)
            if field in ("distance", "dist", "track") and source == "fit"
            else None
        ),
        _range_cache=cache,
    )


def test_real_edit_export_and_final_preparation_parity(real_12):
    _path, _records, dataset = real_12
    layout = {"indicators": {"dist_visual": {
        "enabled": True,
        "form": "bar",
        "bar_style": "ruler",
        "field": "distance",
        "source": "fit",
        "unit": "km",
        "auto_scale": True,
    }}}
    telemetry = _telemetry(dataset)

    edit_owner = SimpleNamespace(telemetry=telemetry, layout=layout)
    PreviewMixin._build_prepare_cache(edit_owner)

    export_controller = SimpleNamespace(telemetry=telemetry, layout=layout)
    export_owner = SimpleNamespace(
        _controller=export_controller, _hud_prepare_cache=None
    )
    RenderTab._build_hud_prepare_cache(export_owner)

    final_cache = build_activity_range_cache(
        layout,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        gpx_speed_samples=[],
        gpx_track_samples=[],
        gpx_alt_samples=[],
        fit_data=dataset,
    )

    distance = resolve_distance_samples("fit", fit_data=dataset)
    boundary = distance.segment_start_indices[0]
    timestamps = [
        distance[0][0],
        distance[boundary - 1][0] + timedelta(seconds=30),
        distance[boundary][0],
        distance[boundary][0] + timedelta(seconds=21),
        distance[-1][0],
    ]
    for target_dt in timestamps:
        edit = _frame(layout, dataset, edit_owner._prepare_cache, target_dt)
        export = _frame(layout, dataset, export_owner._hud_prepare_cache, target_dt)
        final = _frame(layout, dataset, final_cache, target_dt)

        triples = [edit, export, final]
        assert [frame["distance_m"] for frame in triples] == pytest.approx(
            [edit["distance_m"]] * 3
        )
        assert [frame["max_distance_m"] for frame in triples] == pytest.approx(
            [SESSION_TOTAL_M] * 3
        )
        ranges = [frame["auto_ranges"]["dist_visual"] for frame in triples]
        for effective_range in ranges:
            assert effective_range == pytest.approx((0.0, 14.14873))
        fractions = [
            (frame["distance_m"] / 1000.0 - ranges[index][0])
            / (ranges[index][1] - ranges[index][0])
            for index, frame in enumerate(triples)
        ]
        assert fractions == pytest.approx([fractions[0]] * 3)


def test_real_fixed_fit_matches_normalized_original(real_12):
    fixed_path = _required_real_path("TELEM_REAL_12_FIXED_FIT")
    fixed_records = parse_fit(fixed_path)
    assert fixed_records is not None
    fixed_dataset = sync_fit_to_video(
        fixed_records, fixed_records[0]["timestamp"]
    )
    original = resolve_distance_samples("fit", fit_data=real_12[2])
    fixed = resolve_distance_samples("fit", fit_data=fixed_dataset)

    assert fixed_dataset.distance_normalization.segments == 1
    assert fixed_dataset.distance_normalization.resets == 0
    assert fixed_dataset.distance_normalization.normalized_final == pytest.approx(
        SESSION_TOTAL_M
    )
    assert [timestamp for timestamp, _value in fixed] == [
        timestamp for timestamp, _value in original
    ]
    assert [value for _timestamp, value in fixed] == pytest.approx(
        [value for _timestamp, value in original], abs=1e-9
    )
