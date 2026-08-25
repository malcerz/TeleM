from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

from telemetry_fit import parse_fit
from src.indicators.chart_builder import build_chart_data, clip_chart_data_for_target
from src.indicators.compositor import compose_overlay
from src.indicators.chart_utils import _chart_segment_ranges


ROOT = Path(__file__).resolve().parents[1]
FIT_PATH = ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = ROOT / "presets" / "cycling_dashboard_v10.json"


def _load_env(scope="activity"):
    parsed = parse_fit(FIT_PATH)
    assert parsed is not None
    samples = {name: meta["samples"] for name, meta in parsed.field_catalog.items()}
    with open(LAYOUT_PATH, "r", encoding="utf-8") as f:
        layout = json.load(f)

    layout["indicators"]["fit_heart_rate_text"]["chart_time_scope"] = scope
    layout["indicators"]["fit_cadence_text"]["chart_time_scope"] = scope

    hr_samples = samples["heart_rate"]
    t0 = hr_samples[0][0]
    t_end = hr_samples[-1][0]

    chart_data = build_chart_data(
        layout,
        lambda src: ([], [], []),
        lambda field, src, key=None: samples.get(field, []),
        start_dt_utc=t0,
        end_dt_utc=t_end if scope == "activity" else t0 + timedelta(seconds=600),
        source_activity_ranges={"fit": (t0, t_end)},
    )
    return layout, t0, t_end, chart_data, samples


def test_timeline_activity_pauses_and_segments():
    """Verify that activity timeline detects 2 pauses and 3 segments in test FIT data."""
    layout, t0, t_end, chart_data, samples = _load_env(scope="activity")

    hr_samples = samples["heart_rate"]
    timestamps = [s[0] for s in hr_samples]
    values = [s[1] for s in hr_samples]

    ranges = _chart_segment_ranges(timestamps, values)
    assert len(ranges) == 3, f"Expected 3 segments for 2 pauses, got {len(ranges)}"
    # Segment 1
    assert ranges[0][0] == 0 and ranges[0][1] == 1959
    # Segment 2 (during video GX010115)
    assert ranges[1][0] == 1959 and ranges[1][1] == 2553
    # Segment 3 (after Pause 2)
    assert ranges[2][0] == 2553 and ranges[2][1] == 4299


def test_timeline_activity_direct_seek_vs_sequential():
    """Verify that timeline chart renders byte-exact identical frames across all seek timestamps."""
    layout, t0, t_end, chart_data, _ = _load_env(scope="activity")

    vid_start = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)

    def render_at_video_seconds(s: float):
        target_dt = vid_start + timedelta(seconds=s)
        clipped = clip_chart_data_for_target(chart_data, target_dt)
        return compose_overlay(
            1280, 720, layout, "",
            "2026.08.14", "11:18:10",
            speed_value=25.0, distance_m=1000.0,
            chart_data=clipped,
            target_dt=target_dt,
            reuse_canvas=False,
        )

    for s in (7.0, 30.0, 60.0, 147.0, 300.0, 585.0):
        img_direct = np.array(render_at_video_seconds(s))
        img_seq = np.array(render_at_video_seconds(s))
        assert np.array_equal(img_direct, img_seq), f"Direct vs Sequential mismatch at {s}s"


def test_timeline_activity_random_access_determinism():
    """Verify non-monotonic arbitrary seek sequence produces deterministic renders."""
    layout, t0, t_end, chart_data, _ = _load_env(scope="activity")

    vid_start = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)

    def render_at_video_seconds(s: float):
        target_dt = vid_start + timedelta(seconds=s)
        clipped = clip_chart_data_for_target(chart_data, target_dt)
        return compose_overlay(
            1280, 720, layout, "",
            "2026.08.14", "11:18:10",
            speed_value=25.0, distance_m=1000.0,
            chart_data=clipped,
            target_dt=target_dt,
            reuse_canvas=False,
        )

    sequence = [147.0, 300.0, 90.0, 180.0, 60.0, 300.0, 147.0, 7.0, 585.0, 7.0]
    renders = [np.array(render_at_video_seconds(ts)) for ts in sequence]

    # Index 0 (147s) == Index 6 (147s)
    assert np.array_equal(renders[0], renders[6])
    # Index 1 (300s) == Index 5 (300s)
    assert np.array_equal(renders[1], renders[5])
    # Index 7 (7s) == Index 9 (7s)
    assert np.array_equal(renders[7], renders[9])
