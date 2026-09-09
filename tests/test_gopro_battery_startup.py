from datetime import datetime, timedelta, timezone

from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker
from src.telemetry_resolver import presentation_value


BASE = datetime(2026, 9, 2, 4, 22, 38, tzinfo=timezone.utc)


def _samples(first=BASE):
    return [
        (first, 53.0),
        (first + timedelta(seconds=10), 52.0),
    ]


def test_gopro_plan_is_available_at_video_start_and_not_before_first_sample():
    samples = _samples(BASE + timedelta(seconds=3))
    assert presentation_value(
        samples, BASE, "gopro_battery", effective_precision=2,
    ) is None
    assert presentation_value(
        samples, BASE + timedelta(seconds=3), "gopro_battery", effective_precision=2,
    ) == 53.0


def test_worker_warms_gopro_plan_before_first_resolve():
    samples = _samples()
    init_worker(
        1280, 720, "", {"indicators": {}}, {}, fit_data={"gopro_battery": samples},
        start_dt_utc=BASE, target_fps=30.0, total_overlay_frames=300,
    )
    try:
        value = _resolve_cache_value(
            "gopro_battery", "fit", BASE, "fit_gopro_battery_text",
            indicator_config={"decimals": 2},
        )
        assert value is not None
        assert value == 53.0
    finally:
        WORKER_CACHE.clear()
