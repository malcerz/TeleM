from src.ffmpeg.amd_config import make_benchmark_fingerprint, resolve_amd_config
from src.indicators.common_text import (
    classify_common_text_widget,
    common_text_fast_path_is_proven,
)


def test_common_text_flag_is_explicit_and_default_off():
    assert resolve_amd_config({})["common_text_fast"] == 0
    assert resolve_amd_config({"AMD_ABOVE_COMMON_TEXT_FAST": "1"})["common_text_fast"] == 1


def test_common_text_flag_is_in_fingerprint():
    ref = resolve_amd_config({})
    candidate = resolve_amd_config({"AMD_ABOVE_COMMON_TEXT_FAST": "1"})
    assert make_benchmark_fingerprint(ref) != make_benchmark_fingerprint(candidate)


def test_canonical_structured_widgets_are_excluded():
    assert classify_common_text_widget("alt_text", {"form": "bar"}) == "NOT ELIGIBLE"
    assert classify_common_text_widget("speed_text", {"form": "gauge"}) == "NOT ELIGIBLE"
    assert classify_common_text_widget("fit_distance_text", {"form": "bar"}) == "NOT ELIGIBLE"
    assert classify_common_text_widget("fit_heart_rate_text", {"form": "chart"}) == "NOT ELIGIBLE"
    assert classify_common_text_widget("fit_cadence_text", {"form": "chart"}) == "NOT ELIGIBLE"
    assert classify_common_text_widget("fit_gopro_battery_text", {"form": "segment_bar"}) == "NOT ELIGIBLE"


def test_canonical_simple_text_is_exactly_eligible_only_without_extra_art():
    cfg = {"form": "text", "rotation": 0, "icon": "none"}
    assert classify_common_text_widget("iso_text", cfg) == "ELIGIBLE EXACT"
    assert classify_common_text_widget("exposure_text", cfg) == "ELIGIBLE EXACT"
    assert classify_common_text_widget("temp_text", cfg) == "ELIGIBLE EXACT"
    assert classify_common_text_widget("temp_text", {**cfg, "rotation": 90}) == "CONDITIONAL"
    assert not common_text_fast_path_is_proven()
