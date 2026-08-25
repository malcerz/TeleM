from src.ffmpeg.amd_native_exporter import (
    _map_gpu_layout_safe,
    _ordered_map_layout_parts,
)


def _layout(keys):
    return {"indicators": {key: {"enabled": True} for key in keys}}


def test_ordered_map_accepts_map_first_middle_and_last_without_reordering():
    for keys in (("track_map", "speed"), ("speed", "track_map", "hr"), ("speed", "track_map")):
        layout = _layout(keys)
        safe, reason = _map_gpu_layout_safe(layout)
        assert safe is True
        assert "ordered" in reason
        below, above, after = _ordered_map_layout_parts(layout)
        assert list(below["indicators"]) == [key for key in keys if key != "track_map" and keys.index(key) < keys.index("track_map")]
        assert list(above["indicators"]) == [key for key in keys if keys.index(key) > keys.index("track_map")]
        assert after == list(above["indicators"])


def test_unavailable_after_map_indicator_stays_in_above_layer_without_fallback():
    layout = _layout(("track_map", "fit_battery_text"))
    layout["indicators"]["fit_battery_text"]["enabled"] = True
    below, above, after = _ordered_map_layout_parts(layout)
    assert list(below["indicators"]) == []
    assert list(above["indicators"]) == ["fit_battery_text"]
    assert after == ["fit_battery_text"]


def test_ordered_map_preserves_custom_texts_as_above_layer():
    layout = _layout(("speed", "track_map"))
    layout["custom_texts"] = [{"text": "ABOVE"}]
    below, above, _ = _ordered_map_layout_parts(layout)
    assert below["custom_texts"] == []
    assert above["custom_texts"] == layout["custom_texts"]


def test_native_ordered_above_entrypoints_are_present():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "native" / "d3d11_amf_pipeline" / "src" / "telem_amd_native.cpp").read_text(encoding="utf-8")
    vp = (Path(__file__).parents[1] / "native" / "d3d11_amf_pipeline" / "src" / "d3d11_vp_pipeline.cpp").read_text(encoding="utf-8")
    assert "telem_amd_set_above_map_mode" in source
    assert "telem_amd_update_above_map" in source
    assert "BlendAboveMap" in vp
    assert "after GPU_MAP" in vp
