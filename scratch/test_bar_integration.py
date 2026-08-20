import sys, time
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image
from src.indicators.bar import _render_bar_indicator
from src.indicators.dispatcher import render_value_indicator
from src.gui.layout_manager import normalize_layout

def test_bar_rendering():
    layout = normalize_layout(None, 1920, 1080)
    
    # 1. Test Ruler (default)
    print("\n--- 1. Testing Bar Style: RULER ---")
    ruler_cfg = {
        "enabled": True, "label": "Dist", "x": 50.0, "y": 80.0,
        "rotation": 0, "form": "bar", "bar_style": "ruler",
        "size": 25.0, "min_val": 0, "max_val": 100, "major_ticks": 8,
        "minor_ticks": 5, "show_range_labels": True, "show_value": True,
        "show_mid_label": True, "show_label": True,
    }
    img_ruler, rx, ry, extra = _render_bar_indicator(
        1920, 1080, layout, "", "dist_visual", 45.0, "km", "Distance",
        ruler_cfg, 1080, 2, 24, None, 0, 100, 8, 3, int(0.25 * 1920), 1
    )
    print(f"Ruler img size: {img_ruler.size}, rx={rx}, ry={ry}, extra={extra}")
    assert img_ruler is not None, "Ruler render failed"
    assert extra is None, "Extra should be None (local raster annotations)"
    
    # 2. Test Segments
    print("\n--- 2. Testing Bar Style: SEGMENTS ---")
    seg_cfg = {
        "enabled": True, "label": "Battery", "x": 50.0, "y": 50.0,
        "rotation": 0, "form": "bar", "bar_style": "segments",
        "size": 20.0, "min_val": 0, "max_val": 100, "segments": 20,
        "segment_gap": 3, "segment_radius": 2, "inactive_alpha": 90,
        "grow_height": True, "grow_start": 0.5, "show_value": True,
        "show_label": True, "show_min": True, "show_max": True,
    }
    
    # Test values: 0, 1, 25, 50, 75, 100
    for v in [0, 1, 25, 50, 75, 100, -10, 120]:
        img_seg, sx, sy, _ = _render_bar_indicator(
            1920, 1080, layout, "", "battery", v, "%", "Battery",
            seg_cfg, 1080, 2, 24, None, 0, 100, 0, 3, int(0.20 * 1920), 1
        )
        print(f"Segments (val={v:3d}) -> img size: {img_seg.size}, sx={sx}, sy={sy}")
        assert img_seg is not None

    # 3. Test Backward Compatibility: form == "segment_bar"
    print("\n--- 3. Testing Legacy form == 'segment_bar' via Dispatcher ---")
    legacy_cfg = {
        "enabled": True, "label": "Solar", "x": 30.0, "y": 40.0,
        "form": "segment_bar", "size": 15.0, "min_val": 0, "max_val": 100,
        "segments": 10,
    }
    layout["indicators"]["solar"] = legacy_cfg
    img_disp, dx, dy, _ = render_value_indicator(
        1920, 1080, layout, "", "solar", 60.0, "W", "Solar",
        cfg_override=legacy_cfg
    )
    print(f"Dispatcher legacy segment_bar -> img size: {img_disp.size if img_disp else None}")
    assert img_disp is not None, "Dispatcher failed to render legacy segment_bar"

    # 4. Performance Measurement
    print("\n--- 4. Performance benchmark (100 iterations) ---")
    # Ruler
    t0 = time.perf_counter()
    for _ in range(100):
        _render_bar_indicator(
            1920, 1080, layout, "", "dist_visual", 45.0, "km", "Distance",
            ruler_cfg, 1080, 2, 24, None, 0, 100, 8, 3, int(0.25 * 1920), 1
        )
    t1 = time.perf_counter()
    ruler_ms = (t1 - t0) * 10
    print(f"Ruler average render time: {ruler_ms:.3f} ms / frame")

    # Segments
    t0 = time.perf_counter()
    for _ in range(100):
        _render_bar_indicator(
            1920, 1080, layout, "", "battery", 75.0, "%", "Battery",
            seg_cfg, 1080, 2, 24, None, 0, 100, 0, 3, int(0.20 * 1920), 1
        )
    t1 = time.perf_counter()
    seg_ms = (t1 - t0) * 10
    print(f"Segments average render time: {seg_ms:.3f} ms / frame")

    print("\nALL PRELIMINARY UNIT TESTS PASSED!")

if __name__ == "__main__":
    test_bar_rendering()
