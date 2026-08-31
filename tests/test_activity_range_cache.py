from datetime import datetime

from src.telemetry_resolver import build_activity_range_cache


NOW = datetime(2024, 1, 1)


def test_speed_text_fit_range_uses_full_fit_activity_without_gpmf_fallback():
    layout = {"indicators": {"speed_text": {"source": "fit"}}}
    cache = build_activity_range_cache(
        layout,
        speed_samples=[(NOW, 99.0)],
        fit_data={"speed": [(NOW, 12.0), (NOW, 47.5)]},
    )
    assert cache["max_speed_kmh"] == 47.5


def test_empty_selected_source_does_not_borrow_another_source_range():
    layout = {"indicators": {"speed_text": {"source": "fit"}}}
    cache = build_activity_range_cache(
        layout, speed_samples=[(NOW, 99.0)], fit_data={}
    )
    assert cache["max_speed_kmh"] is None


def test_disabled_visual_does_not_override_enabled_speed_text_source():
    layout = {"indicators": {
        "speed_visual": {"enabled": False, "source": "gpmf"},
        "speed_text": {"enabled": True, "source": "fit"},
    }}
    cache = build_activity_range_cache(
        layout,
        speed_samples=[(NOW, 99.0)],
        fit_data={"speed": [(NOW, 45.0)]},
    )
    assert cache["max_speed_kmh"] == 45.0
