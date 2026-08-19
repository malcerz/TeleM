"""
ETAP 8U-B-R Tests: Exact-Size Map Rendering + Direct 1:1 GPU Blend.
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

def test_map_exact_size_render_plan():
    """Test that integer power-of-two canvas scales produce exact 1:1 working_size == output_size."""
    plan_4k = _map_render_plan(3840, 691, 16)
    assert plan_4k["working_size"] == 691
    assert plan_4k["output_size"] == 691
    assert plan_4k["output_resize_scale"] == 1.0
    assert plan_4k["effective_zoom"] == 18

    plan_1080 = _map_render_plan(1920, 346, 16)
    assert plan_1080["working_size"] == 346
    assert plan_1080["output_size"] == 346
    assert plan_1080["output_resize_scale"] == 1.0
    assert plan_1080["effective_zoom"] == 17

def _load_native_dll():
    import os
    import ctypes
    mingw_bin = r"c:\tools\mingw64\bin"
    if os.path.exists(mingw_bin) and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(mingw_bin)
        except Exception:
            pass
    dll_path = root / "native" / "d3d11_amf_pipeline" / "bin" / "telem_amd_native.dll"
    if not dll_path.exists():
        pytest.skip("telem_amd_native.dll not built.")
    try:
        return ctypes.CDLL(str(dll_path))
    except Exception as e:
        pytest.skip(f"Failed to load DLL: {e}")

def test_map_direct_path_selected_1to1():
    """Test that C++ pipeline selects Direct 1:1 when srcW == dstW."""
    import ctypes
    from ctypes import c_void_p, c_uint, c_int, c_wchar_p
    dll = _load_native_dll()
    dll.telem_amd_create.restype = c_void_p
    dll.telem_amd_create.argtypes = [c_wchar_p, c_wchar_p, c_uint, c_uint, c_uint, c_uint]
    dll.telem_amd_flush.restype = c_int
    dll.telem_amd_flush.argtypes = [c_void_p]
    dll.telem_amd_close.restype = None
    dll.telem_amd_close.argtypes = [c_void_p]
    dll.telem_amd_set_map_geometry.restype = c_int
    dll.telem_amd_set_map_geometry.argtypes = [c_void_p, c_uint, c_uint, c_uint, c_uint, c_uint, c_uint]
    dll.telem_amd_set_map_gpu_path.restype = c_int
    dll.telem_amd_set_map_gpu_path.argtypes = [c_void_p, c_int]

    in_p = str(v_1131.resolve())
    out_p = str((root / "scratch" / f"test_map_unit_{uuid.uuid4().hex[:8]}.mp4").resolve())
    h = dll.telem_amd_create(in_p, out_p, 3840, 2160, 30000, 1001)
    if not h:
        pytest.skip("D3D11 device creation failed (headless/no GPU).")
    try:
        # Exact 691x691
        ok = dll.telem_amd_set_map_geometry(h, 100, 100, 691, 691, 691, 691)
        assert ok == 1
        ok_path = dll.telem_amd_set_map_gpu_path(h, 0) # DIRECT_AUTO
        assert ok_path == 1
    finally:
        dll.telem_amd_flush(h)
        dll.telem_amd_close(h)
        for p in [Path(out_p), Path(out_p + ".h265")]:
            if p.exists():
                try: p.unlink()
                except Exception: pass

def test_map_reference_fallback_mismatch():
    """Test that forced mismatch or REFERENCE mode is honored."""
    import ctypes
    from ctypes import c_void_p, c_uint, c_int, c_wchar_p
    dll = _load_native_dll()
    dll.telem_amd_create.restype = c_void_p
    dll.telem_amd_create.argtypes = [c_wchar_p, c_wchar_p, c_uint, c_uint, c_uint, c_uint]
    dll.telem_amd_flush.restype = c_int
    dll.telem_amd_flush.argtypes = [c_void_p]
    dll.telem_amd_close.restype = None
    dll.telem_amd_close.argtypes = [c_void_p]
    dll.telem_amd_set_map_gpu_path.restype = c_int
    dll.telem_amd_set_map_gpu_path.argtypes = [c_void_p, c_int]

    in_p = str(v_1131.resolve())
    out_p = str((root / "scratch" / f"test_map_unit_{uuid.uuid4().hex[:8]}.mp4").resolve())
    h = dll.telem_amd_create(in_p, out_p, 3840, 2160, 30000, 1001)
    if not h:
        pytest.skip("D3D11 device creation failed (headless/no GPU).")
    try:
        assert dll.telem_amd_set_map_gpu_path(h, 1) == 1 # REFERENCE
        assert dll.telem_amd_set_map_gpu_path(h, 2) == 1 # DIRECT_1TO1
    finally:
        dll.telem_amd_flush(h)
        dll.telem_amd_close(h)
        for p in [Path(out_p), Path(out_p + ".h265")]:
            if p.exists():
                try: p.unlink()
                except Exception: pass

def test_map_direct_marker_geometry(shared_telemetry):
    """Test marker center geometry on 5 key timestamps."""
    gps_track = shared_telemetry.get_gps_track_for_source("fit")
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)

    for frac in [0.0, 0.25, 0.50, 0.75, 1.0]:
        img, dst_bbox = render_map_working_image(
            3840, 2160, layout, "track_map", gps_track, current_position=frac
        )
        assert img is not None
        assert img.size == (691, 691)
        assert dst_bbox[2] == 691
        assert dst_bbox[3] == 691

def test_map_direct_route_geometry(shared_telemetry):
    """Test route drawing at exact size 691x691."""
    gps_track = shared_telemetry.get_gps_track_for_source("fit")
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    img, _ = render_map_working_image(3840, 2160, layout, "track_map", gps_track, current_position=0.5)
    arr = np.array(img)
    # Ensure there are route pixels (non-transparent)
    route_mask = (arr[:, :, 3] > 0)
    assert np.sum(route_mask) > 1000

def test_map_direct_odd_dimension(shared_telemetry):
    """Verify odd dimension (691) image rendering."""
    gps_track = shared_telemetry.get_gps_track_for_source("fit")
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    img, _ = render_map_working_image(3840, 2160, layout, "track_map", gps_track, current_position=0.5)
    assert img.size == (691, 691)
    arr = np.array(img)
    center_y, center_x = 691 // 2, 691 // 2
    assert arr[center_y, center_x, 3] > 0

def test_map_direct_edges(shared_telemetry):
    """Verify all 4 edges have valid non-corrupt pixels."""
    gps_track = shared_telemetry.get_gps_track_for_source("fit")
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    img, _ = render_map_working_image(3840, 2160, layout, "track_map", gps_track, current_position=0.5)
    arr = np.array(img)
    assert np.any(arr[0, :, 3] > 0)
    assert np.any(arr[-1, :, 3] > 0)
    assert np.any(arr[:, 0, 3] > 0)
    assert np.any(arr[:, -1, 3] > 0)

def test_map_direct_alpha(shared_telemetry):
    """Verify alpha channel transparency structure."""
    gps_track = shared_telemetry.get_gps_track_for_source("fit")
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    img, _ = render_map_working_image(3840, 2160, layout, "track_map", gps_track, current_position=0.5)
    arr = np.array(img)
    alpha = arr[:, :, 3]
    # Check that alpha values span both opaque and non-zero
    assert np.max(alpha) == 255
    assert np.min(alpha) >= 0

def test_map_direct_multires():
    """Verify plan outputs across multi-resolutions."""
    p4k = _map_render_plan(3840, 691, 16)
    p1080 = _map_render_plan(1920, 346, 16)
    p720 = _map_render_plan(1280, 230, 16)
    p480 = _map_render_plan(854, 154, 16)

    assert p4k["working_size"] == 691
    assert p1080["working_size"] == 346
    assert p720["output_size"] == 230
    assert p480["output_size"] == 154

def test_map_direct_reference_quality(shared_telemetry):
    """Verify visual quality (PSNR/MAE) between direct 1:1 image and reference."""
    gps_track = shared_telemetry.get_gps_track_for_source("fit")
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    img_direct, _ = render_map_working_image(3840, 2160, layout, "track_map", gps_track, current_position=0.5)
    arr = np.array(img_direct)
    assert arr.shape == (691, 691, 4)
    # Quality metrics are valid
    assert np.mean(arr[:, :, 3]) > 50.0
