from datetime import datetime, timedelta

from src.ffmpeg.streaming import _report_stream_progress
from src.indicators.chart_utils import _split_chart_segments


def test_stream_progress_supplies_preview_timestamp():
    events = []
    _report_stream_progress(50, 100, 1.0, None, lambda *args: events.append(args), 25.0)
    assert events[0][0:2] == (50, 100)
    assert events[0][4] == {"frame": 49, "ts": 49 / 25.0}


def test_chart_gap_and_missing_are_not_joined():
    ts0 = datetime(2026, 1, 1)
    timestamps = [ts0, ts0 + timedelta(seconds=1), ts0 + timedelta(seconds=20), ts0 + timedelta(seconds=21)]
    points = [(0.0, 10.0), (1.0, 9.0), (2.0, 8.0), (3.0, 7.0)]
    segments = _split_chart_segments(points, timestamps, [10.0, None, 8.0, 0.0])
    assert segments == [[points[0]], [points[1]], [points[2], points[3]]]


def test_chart_data_semantics_keep_none_zero_and_order():
    samples = [
        (ts0 := datetime(2026, 1, 1), 10.0),
        (ts0 + timedelta(seconds=1), None),
        (ts0 + timedelta(seconds=2), 0.0),
    ]
    semantic = [(ts, value, value is None) for ts, value in samples]
    assert semantic[1][1] is None
    assert semantic[2][1] == 0.0
    assert [item[0] for item in semantic] == sorted(item[0] for item in semantic)
