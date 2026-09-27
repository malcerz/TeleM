import os
import sys
import ctypes
import pytest
from pathlib import Path

workspace_root = Path(__file__).resolve().parent.parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from src.ffmpeg.intel_native_exporter import (
    IntelNativePipelineStats,
    _load_native_intel_dll,
)


def test_intel_7k_stats_struct_fields():
    """Verify that IntelNativePipelineStats matches 7K dual device and true metric definitions."""
    fields = dict(IntelNativePipelineStats._fields_)
    assert "total_p010_map_ms" in fields
    assert "total_p010_pure_convert_ms" in fields
    assert "total_p010_unmap_ms" in fields
    assert "total_p010_cycles" in fields
    assert "total_producer_cycles" in fields
    assert "total_consumer_cycles" in fields
    assert "map_hist_counts" in fields
    assert "map_p50_ms" in fields
    assert "map_p95_ms" in fields
    assert "map_p99_ms" in fields
    assert "total_cross_copy_ms" in fields
    assert "total_cross_wait_producer_ms" in fields
    assert "total_cross_wait_consumer_ms" in fields


def test_intel_7k_dll_load_and_exports():
    """Verify that telem_intel_native.dll loads and exposes all required 7K entrypoints."""
    lib = _load_native_intel_dll()
    assert hasattr(lib, "intel_d3d11_vp_init")
    assert hasattr(lib, "intel_d3d11_vp_cleanup")
    assert hasattr(lib, "intel_native_pipeline_init")
    assert hasattr(lib, "intel_native_pipeline_init_multi")
    assert hasattr(lib, "intel_native_pipeline_step")
    assert hasattr(lib, "intel_native_pipeline_finish")
    assert hasattr(lib, "intel_native_pipeline_cancel")
    assert hasattr(lib, "intel_native_pipeline_get_stats")


def test_intel_7k_dual_device_toggle():
    """Verify that TELEM_INTEL_DUAL_DEVICE environment variable is respected."""
    lib = _load_native_intel_dll()
    
    # Init with DUAL_DEVICE=0
    os.environ["TELEM_INTEL_DUAL_DEVICE"] = "0"
    ret0 = lib.intel_d3d11_vp_init()
    assert ret0 == 0
    lib.intel_d3d11_vp_cleanup()

    # Init with DUAL_DEVICE=1
    os.environ["TELEM_INTEL_DUAL_DEVICE"] = "1"
    ret1 = lib.intel_d3d11_vp_init()
    assert ret1 == 0
    lib.intel_d3d11_vp_cleanup()


def test_intel_7k_error_handling_nonexistent_file():
    """Verify clean error code return when invalid video file is passed."""
    lib = _load_native_intel_dll()
    out_ivf = str(workspace_root / "scratch" / "test_error_7k.ivf")
    ret = lib.intel_native_pipeline_init(
        b"Video/NON_EXISTENT_FILE_7K.MP4",
        out_ivf.encode("utf-8"),
        40000, 50000, 100
    )
    assert ret != 0, "Nonexistent input file must return non-zero error code"
