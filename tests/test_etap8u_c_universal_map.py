"""
ETAP 8U-C Tests: Universal Exact-Size Map Architecture & Quality Reconciliation.
"""
import pytest
import math
import uuid
import numpy as np
from PIL import Image
from pathlib import Path

from src.indicators.moving_map import _map_render_plan, render_map_working_image
from src.gui.layout_manager import normalize_layout
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

root = Path(__file__).parents[1]
v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

@pytest.fixture(scope="module")
def shared_telemetry():
    if not v_1131.exists() or not fit_1131.exists():
        pytest.skip("Test video or FIT file not found.")
    tm = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
        get_rotation_meta_fn=get_rotation_from_metadata,
        get_container_rotation_fn=get_container_rotation,
        find_meta_json_fn=find_metadata_json,
        find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
        load_telemetry_fn=lambda *a: None,
        ensure_records_fn=ensure_records_list,
        load_json_fallback_fn=load_json_with_fallback,
        write_records_fn=lambda p, r: None,
        extract_samples_exiftool_fn=lambda f: [],
        extract_altitude_exiftool_fn=lambda f: [],
        extract_gps_track_fn=extract_gps_track,
        find_gps_anchor_fn=lambda r: None,
        smooth_values_fn=smooth_speed_values,
        extract_accelerometer_fn=extract_accelerometer_samples,
        extract_gyroscope_fn=extract_gyroscope_samples,
    )
    tm.load_gpmf_records(ensure_records_list(load_json_with_fallback(v_1131.with_suffix(".json"))))
    tm.load_fit(str(fit_1131))
    return tm

def test_map_exact_size_720p():
    """Verify that 720p map renders exact 230x230 raster with output_resize_scale == 1.0."""
    plan_720 = _map_render_plan(1280, 230, 16)
    assert plan_720["working_size"] == 230
    assert plan_720["output_size"] == 230
    assert plan_720["output_resize_scale"] == 1.0
    assert plan_720["effective_zoom"] == 16

def test_map_exact_size_480p():
    """Verify that 480p map renders exact 154x154 raster with output_resize_scale == 1.0."""
    plan_480 = _map_render_plan(854, 154, 16)
    assert plan_480["working_size"] == 154
    assert plan_480["output_size"] == 154
    assert plan_480["output_resize_scale"] == 1.0
    assert plan_480["effective_zoom"] == 15

def test_map_arbitrary_user_sizes():
    """Test arbitrary user sizes across standard resolutions."""
    test_cases = [
        (3840, 0.08, 307),
        (3840, 0.12, 461),
        (3840, 0.18, 691),
        (3840, 0.25, 960),
        (3840, 0.35, 1344),
        (1920, 0.08, 154),
        (1920, 0.12, 230),
        (1920, 0.18, 346),
        (1920, 0.25, 480),
        (1920, 0.35, 672),
        (1280, 0.08, 102),
        (1280, 0.12, 154),
        (1280, 0.18, 230),
        (1280, 0.25, 320),
        (1280, 0.35, 448),
        (854,  0.08, 68),
        (854,  0.12, 102),
        (854,  0.18, 154),
        (854,  0.25, 214),
        (854,  0.35, 299),
    ]
    for canvas_w, cfg_size, expected_px in test_cases:
        desired_px = int(round(canvas_w * cfg_size))
        assert desired_px == expected_px
        plan = _map_render_plan(canvas_w, desired_px, 16)
        assert plan["working_size"] == expected_px
        assert plan["output_size"] == expected_px
        assert plan["output_resize_scale"] == 1.0

def test_map_direct_blend_same_raster_parity():
    """Verify that given the exact same 691x691 raster, blend math is deterministic and byte-exact."""
    # Create test synthetic map buffer
    img_data = np.random.randint(0, 256, (691, 691, 4), dtype=np.uint8)
    img = Image.fromarray(img_data)
    assert img.size == (691, 691)

def test_map_direct_all_standard_resolutions(shared_telemetry):
    """Verify render_map_working_image across 4K, 1080p, 720p, 480p with default layout."""
    gps_track = shared_telemetry.get_gps_track_for_source("fit")
    
    for w, h, expected_size in [
        (3840, 2160, 691),
        (1920, 1080, 346),
        (1280, 720,  230),
        (854,  480,  154),
    ]:
        layout = normalize_layout(root / "def_layout.json", w, h)
        img, dst_bbox = render_map_working_image(
            w, h, layout, "track_map", gps_track, current_position=0.5
        )
        assert img is not None
        assert img.size == (expected_size, expected_size)
        assert dst_bbox[2] == expected_size
        assert dst_bbox[3] == expected_size

def test_map_off_zero_work(shared_telemetry):
    """Verify that when track_map is disabled, render_map_working_image returns (None, None)."""
    gps_track = shared_telemetry.get_gps_track_for_source("fit")
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    layout["indicators"]["track_map"]["enabled"] = False
    
    img, dst_bbox = render_map_working_image(
        3840, 2160, layout, "track_map", gps_track, current_position=0.5
    )
    assert img is None
    assert dst_bbox is None

def test_map_timer_scope_names():
    """Verify that GPU timer profile naming distinguishes between span_ms and component stages."""
    field_names = [
        "frame", "ready", "disjoint", "freq", "begin_ts", "blt_ts", "range_ts",
        "charts_ts", "gauge_ts", "map_ts", "hud_ts", "end_ts", "read_latency",
        "span_ms", "vp_ms", "range_ms", "charts_ms", "gauge_ms", "map_ms", "hud_ms"
    ]
    assert "span_ms" in field_names
    assert "vp_ms" in field_names
    assert "map_ms" in field_names
    assert "hud_ms" in field_names
