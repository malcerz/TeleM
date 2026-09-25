"""Unit tests for generic per-widget CPU render cache with canonical visual state."""

import pytest
from src.indicators.widget_cache import (
    WidgetRenderCache,
    compute_visual_signature,
    reset_widget_cache,
)


def _render_sig(
    key: str,
    renderer_type: str,
    val: float | None,
    cfg: dict,
    formatted_val: str | None = None,
    unit: str = "%",
    label: str = "Battery",
    val_min: float = 0.0,
    val_max: float = 100.0,
    size_px: int = 100,
    fs: int = 20,
    outline: int = 1,
    ss: int = 1,
    canvas_w: int = 3840,
    canvas_h: int = 2160,
    font_path: str = "default.ttf",
) -> tuple:
    return compute_visual_signature(
        renderer_type=renderer_type,
        value=val,
        formatted_val=formatted_val,
        unit=unit,
        label=label,
        cfg=cfg,
        val_min=val_min,
        val_max=val_max,
        size_px=size_px,
        fs=fs,
        outline=outline,
        ss=ss,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        font_path=font_path,
        key=key,
    )


def test_interpolated_raw_values_canonical_state():
    """Test raw values [83.12, 83.14, 83.16, 83.51, 84.01] with canonical visual state."""
    cache = WidgetRenderCache(enabled=True)
    cfg = {"segments": 30, "segment_gap": 3, "decimals": 0, "show_value": True}
    raw_vals = [83.12, 83.14, 83.16, 83.51, 84.01]

    actual_results = []
    signatures = []

    for val in raw_vals:
        formatted = f"{val:.0f}%"
        sig = _render_sig("garmin_bat", "segment_bar", val, cfg, formatted_val=formatted)
        signatures.append(sig)

        inst = cache.instances.get("garmin_bat")
        misses_before = inst.stats.misses if inst else 0

        cache.get_or_render(
            instance_key="garmin_bat",
            renderer_type="segment_bar",
            compute_sig_fn=lambda s=sig: s,
            render_fn=lambda: ("img", 10, 20, None),
            raw_value=val,
        )

        inst = cache.instances["garmin_bat"]
        actual_results.append("MISS" if inst.stats.misses > misses_before else "HIT")

    # Signatures for 83.12, 83.14, 83.16 must be IDENTICAL (value_text='83%', active=25)
    assert signatures[0] == signatures[1] == signatures[2]
    # 83.51 produces value_text='84%', active=26 -> DIFFERENT signature
    assert signatures[3] != signatures[2]

    # Verify expected sequence derived directly from signature changes
    expected = ["MISS"]
    for i in range(1, len(signatures)):
        expected.append("MISS" if signatures[i] != signatures[i - 1] else "HIT")

    assert actual_results == expected
    assert actual_results[:3] == ["MISS", "HIT", "HIT"]

    stats = cache.instances["garmin_bat"].stats
    assert stats.raw_value_changes == 5
    assert stats.visual_state_changes == len([x for x in expected if x == "MISS"])


def test_fast_changing_power_sequence():
    """Power values [100, 101, 102, 103] with changing text -> MISS, MISS, MISS, MISS."""
    cache = WidgetRenderCache(enabled=True)
    cfg = {"segments": 20, "segment_gap": 3, "show_value": True}
    seq = [100.0, 101.0, 102.0, 103.0]
    expected_results = ["MISS", "MISS", "MISS", "MISS"]
    actual_results = []

    for val in seq:
        formatted = f"{val:.0f} W"
        sig_fn = lambda v=val, f=formatted: _render_sig(
            "power_inst", "segment_bar", v, cfg, formatted_val=f, unit="W", label="Power",
        )

        inst = cache.instances.get("power_inst")
        misses_before = inst.stats.misses if inst else 0

        cache.get_or_render(
            instance_key="power_inst",
            renderer_type="segment_bar",
            compute_sig_fn=sig_fn,
            render_fn=lambda: ("img_power", 10, 20, None),
            raw_value=val,
        )

        inst = cache.instances["power_inst"]
        actual_results.append("MISS" if inst.stats.misses > misses_before else "HIT")

    assert actual_results == expected_results
    inst_stats = cache.instances["power_inst"].stats
    assert inst_stats.hits == 0
    assert inst_stats.misses == 4
    assert inst_stats.raw_value_changes == 4
    assert inst_stats.visual_state_changes == 4


def test_config_and_layout_invalidation():
    """Changing segment_count, min/max, colors, thresholds, fonts, orientation, geometry, precision, or unit invalidates cache."""
    cache = WidgetRenderCache(enabled=True)
    base_cfg = {"segments": 10, "segment_color": "#00FF00", "decimals": 0, "orientation": "horizontal"}

    # Initial render
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, base_cfg), lambda: ("img1", 0, 0, None))
    # Same value, same cfg -> HIT
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, base_cfg), lambda: ("img1", 0, 0, None))
    assert cache.instances["inst"].stats.hits == 1
    assert cache.instances["inst"].stats.misses == 1

    # 1. Change segment_count
    cfg_seg = dict(base_cfg, segments=20)
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, cfg_seg), lambda: ("img2", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 2

    # 2. Change min_val / max_val
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, base_cfg, val_min=10.0, val_max=200.0), lambda: ("img2b", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 3

    # 3. Change color
    cfg_color = dict(base_cfg, segment_color="#FF0000")
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, cfg_color), lambda: ("img3", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 4

    # 4. Change threshold
    cfg_thresh = dict(base_cfg, segment_thresholds=[{"value": 50, "color": "#FFFF00"}])
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, cfg_thresh), lambda: ("img4", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 5

    # 5. Change font
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, base_cfg, font_path="custom.ttf"), lambda: ("img5", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 6

    # 6. Change orientation
    cfg_orient = dict(base_cfg, orientation="vertical")
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, cfg_orient), lambda: ("img6", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 7

    # 7. Change geometry (size_px)
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, base_cfg, size_px=200), lambda: ("img7", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 8

    # 8. Change precision (decimals)
    cfg_dec = dict(base_cfg, decimals=2)
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, cfg_dec), lambda: ("img8", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 9

    # 9. Change unit
    cache.get_or_render("inst", "segment_bar", lambda: _render_sig("inst", "segment_bar", 50, base_cfg, unit="W"), lambda: ("img9", 0, 0, None))
    assert cache.instances["inst"].stats.misses == 10


def test_per_instance_isolation():
    """Instance A and Instance B have independent cache states."""
    cache = WidgetRenderCache(enabled=True)
    cfgA = {"segments": 5}
    cfgB = {"segments": 10}

    # Frame 1: A=50, B=20
    cache.get_or_render("A", "segment_bar", lambda: _render_sig("A", "segment_bar", 50, cfgA), lambda: ("imgA", 0, 0, None), raw_value=50)
    cache.get_or_render("B", "segment_bar", lambda: _render_sig("B", "segment_bar", 20, cfgB), lambda: ("imgB", 0, 0, None), raw_value=20)

    # Frame 2: A=50 (HIT), B=50 (MISS due to value change from 20 to 50)
    cache.get_or_render("A", "segment_bar", lambda: _render_sig("A", "segment_bar", 50, cfgA), lambda: ("imgA", 0, 0, None), raw_value=50)
    cache.get_or_render("B", "segment_bar", lambda: _render_sig("B", "segment_bar", 50, cfgB), lambda: ("imgB", 0, 0, None), raw_value=50)

    assert cache.instances["A"].stats.hits == 1
    assert cache.instances["A"].stats.misses == 1
    assert cache.instances["B"].stats.hits == 0
    assert cache.instances["B"].stats.misses == 2
