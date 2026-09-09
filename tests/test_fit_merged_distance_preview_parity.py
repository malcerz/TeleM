from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from telemetry_fit import FitRecords, sync_fit_to_video
from src.gui.qt._mixins.preview_mixin import PreviewMixin
from src.indicators.frame_data import (
    compute_indicator_auto_ranges,
    prepare_overlay_frame_data,
)
from src.telemetry_extract import interpolate_distance
from src.telemetry_precompute import _vectorize_linear_distance
from src.telemetry_resolver import (
    build_activity_range_cache,
    normalize_fit_recorded_distance,
    resolve_distance_samples,
)


BASE = datetime(2026, 9, 1, 13, 7, 12, tzinfo=timezone.utc)


def _full_merged_stream():
    return [
        (BASE, 0.0),
        (BASE + timedelta(minutes=20, seconds=51), 6371.32),
        (BASE + timedelta(minutes=23, seconds=12), 0.0),
        (BASE + timedelta(minutes=40), 7777.41),
    ]


def test_merged_fit_distance_normalizes_to_session_total():
    normalized = normalize_fit_recorded_distance(
        _full_merged_stream(), session_total=14148.73
    )
    assert normalized.normalization is not None
    assert normalized.normalization.segments == 2
    assert normalized.normalization.resets == 1
    assert normalized.normalization.segment_ends == pytest.approx((6371.32, 7777.41))
    assert normalized[-1][1] == pytest.approx(14148.73)
    assert normalized.normalization.match is True
    assert all(b[1] >= a[1] for a, b in zip(normalized, normalized[1:]))


def test_gap_holds_last_value_until_first_record_of_second_segment():
    t0 = BASE
    t1 = t0 + timedelta(seconds=1)
    t2 = t1 + timedelta(seconds=141)
    t3 = t2 + timedelta(seconds=1)
    normalized = normalize_fit_recorded_distance([
        (t0, 6300.0),
        (t1, 6371.32),
        (t2, 0.0),
        (t3, 100.0),
    ])

    probes = [t1 + timedelta(seconds=offset) for offset in (1, 70, 140)]
    assert all(interpolate_distance(normalized, probe) == pytest.approx(6371.32) for probe in probes)
    assert interpolate_distance(normalized, t2) == pytest.approx(6371.32)
    assert interpolate_distance(normalized, t3) == pytest.approx(6471.32)
    values = [interpolate_distance(normalized, t0 + timedelta(seconds=i)) for i in range(143)]
    assert all(b >= a for a, b in zip(values, values[1:]))


def test_vectorized_precompute_has_the_same_gap_hold_contract():
    np = pytest.importorskip("numpy")
    t0 = BASE.replace(tzinfo=None)
    t1 = t0 + timedelta(seconds=1)
    t2 = t1 + timedelta(seconds=141)
    t3 = t2 + timedelta(seconds=1)
    normalized = normalize_fit_recorded_distance([
        (t0, 6300.0), (t1, 6371.32), (t2, 0.0), (t3, 100.0),
    ])
    target_dts = [t1 + timedelta(seconds=1), t1 + timedelta(seconds=140), t2, t3]
    target_ts = np.array([(dt - t0).total_seconds() for dt in target_dts])
    values = _vectorize_linear_distance(normalized, target_dts, target_ts, t0)
    assert values == pytest.approx([6371.32, 6371.32, 6371.32, 6471.32])


def test_sync_logs_required_diagnostic_once_and_preserves_metadata(capsys):
    records = FitRecords(
        [
            {"timestamp": timestamp.replace(tzinfo=None), "distance": distance}
            for timestamp, distance in _full_merged_stream()
        ],
        session_total_distance=14148.73,
        lap_summaries=[
            {"start_time": BASE, "total_distance": 6371.32},
            {"start_time": BASE + timedelta(minutes=23, seconds=12), "total_distance": 7777.41},
        ],
    )
    dataset = sync_fit_to_video(records, BASE)
    output = capsys.readouterr().out

    assert output.count("[FIT DISTANCE NORMALIZE]") == 1
    assert "segments=2" in output
    assert "resets=1" in output
    assert "segment_ends=[6371.32,7777.41]" in output
    assert "normalized_final=14148.73" in output
    assert "session_total=14148.73" in output
    assert "match=True" in output
    assert dataset.session_total_distance == pytest.approx(14148.73)
    assert len(dataset.lap_summaries) == 2
    assert dataset["distance"][-1][1] == pytest.approx(14148.73)


def test_edit_preview_and_render_use_same_current_range_and_marker_fraction():
    canonical = normalize_fit_recorded_distance(
        _full_merged_stream(), session_total=14148.73
    )
    absurd_track = [(timestamp, distance * 80.0) for timestamp, distance in _full_merged_stream()]
    fit_data = {"distance": canonical, "track": absurd_track}
    layout = {"indicators": {"dist_visual": {
        "enabled": True,
        "form": "bar",
        "bar_style": "ruler",
        "field": "distance",
        "source": "fit",
        "unit": "km",
        "auto_scale": True,
    }}}

    telemetry = SimpleNamespace(
        speed_samples=[], track_samples=[], alt_samples=[],
        gpx_speed_samples=[], gpx_track_samples=[], gpx_alt_samples=[],
        fit_data=fit_data,
        iso_samples=[], exposure_samples=[], temperature_samples=[],
        gpx_power_samples=[], gpx_atemp_samples=[], gpx_hr_samples=[],
        gpx_cad_samples=[],
    )
    preview_owner = SimpleNamespace(telemetry=telemetry, layout=layout)
    PreviewMixin._build_prepare_cache(preview_owner)

    render_cache = build_activity_range_cache(
        layout,
        speed_samples=[], track_samples=[], alt_samples=[],
        gpx_speed_samples=[], gpx_track_samples=[], gpx_alt_samples=[],
        fit_data=fit_data,
    )
    render_cache["auto_ranges"] = compute_indicator_auto_ranges(
        layout, fit_data=fit_data
    )
    target = BASE + timedelta(minutes=23, seconds=13)

    def frame(cache):
        return prepare_overlay_frame_data(
            layout=layout,
            target_dt=target,
            tz_offset_hours=0.0,
            start_dt_utc=BASE,
            speed_samples=[], track_samples=[], alt_samples=[],
            fit_data=fit_data,
            resolve_cache_value=lambda field, source, when, key=None: (
                interpolate_distance(
                    resolve_distance_samples(source, fit_data=fit_data), when
                ) if field in ("distance", "dist", "track") else None
            ),
            _range_cache=cache,
        )

    preview_frame = frame(preview_owner._prepare_cache)
    render_frame = frame(render_cache)
    assert preview_frame["distance_m"] == pytest.approx(render_frame["distance_m"])
    assert preview_frame["max_distance_m"] == pytest.approx(14148.73)
    assert preview_frame["max_distance_m"] == pytest.approx(render_frame["max_distance_m"])
    assert preview_frame["auto_ranges"]["dist_visual"] == pytest.approx(
        render_frame["auto_ranges"]["dist_visual"]
    )

    minimum, maximum = preview_frame["auto_ranges"]["dist_visual"]
    preview_fraction = (preview_frame["distance_m"] / 1000.0 - minimum) / (maximum - minimum)
    render_fraction = (render_frame["distance_m"] / 1000.0 - minimum) / (maximum - minimum)
    assert preview_fraction == pytest.approx(render_fraction)

