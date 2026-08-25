from src.ffmpeg.amd_native_exporter import _layout_has_hud


def test_layout_has_hud_for_enabled_indicator():
    assert _layout_has_hud({"indicators": {"speed": {"enabled": True}}})


def test_layout_has_no_hud_when_all_indicators_are_disabled():
    layout = {
        "indicators": {"speed": {"enabled": False}},
        "custom_texts": [{"enabled": False, "text": "hidden"}],
    }
    assert not _layout_has_hud(layout)


def test_layout_has_no_hud_for_empty_custom_text():
    assert not _layout_has_hud({"indicators": {}, "custom_texts": [{"enabled": True, "text": ""}]})


def test_layout_has_hud_for_enabled_nonempty_custom_text():
    assert _layout_has_hud({"indicators": {}, "custom_texts": [{"enabled": True, "text": "Telemetry"}]})
