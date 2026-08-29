"""ETAP 5M chart precompute lifetime and stale-cache regression tests."""

from datetime import datetime, timedelta, timezone

from src.ffmpeg.worker_cache import WORKER_CACHE, init_worker


BASE = datetime(2026, 8, 5, 4, 28, 11, tzinfo=timezone.utc)


def _init_dataset(cadence_start: float, heart_rate_start: float) -> dict:
    layout = {
        "indicators": {
            "fit_cadence_text": {
                "enabled": True, "form": "chart", "source": "fit",
            },
            "fit_heart_rate_text": {
                "enabled": True, "form": "chart", "source": "fit",
            },
        }
    }
    fit_data = {
        "cadence": [(BASE + timedelta(seconds=i), cadence_start + i) for i in range(4)],
        "heart_rate": [(BASE + timedelta(seconds=i), heart_rate_start + i) for i in range(4)],
    }
    init_worker(
        video_width=1920, video_height=1080, font_path="", layout=layout,
        field_samples={}, fit_data=fit_data, start_dt_utc=BASE,
        target_fps=1.0, total_overlay_frames=4,
    )
    return WORKER_CACHE["_precomputed_chart_data"]


def test_first_second_and_restarted_export_use_their_own_chart_data():
    data_a = _init_dataset(80.0, 140.0)
    assert list(data_a["fit_cadence_text"]) == [80.0, 81.0, 82.0, 83.0]
    assert list(data_a["fit_heart_rate_text"]) == [140.0, 141.0, 142.0, 143.0]

    # A new init_worker call represents a new export after completion or
    # cancel/restart. The cache must be replaced, not inherited.
    data_b = _init_dataset(180.0, 240.0)
    assert list(data_b["fit_cadence_text"]) == [180.0, 181.0, 182.0, 183.0]
    assert list(data_b["fit_heart_rate_text"]) == [240.0, 241.0, 242.0, 243.0]
    assert data_b is WORKER_CACHE["_precomputed_chart_data"]
    assert list(data_b["fit_cadence_text"]) != list(data_a["fit_cadence_text"])
