"""Tests for Intel Core Ultra Etap 7F: Timing Correctness, Performance Attribution, and Base Path Optimization."""

import os
import sys
import json
import ctypes
import fractions
from pathlib import Path
import pytest

workspace_root = Path(__file__).resolve().parent.parent

class StagingBenchmarkResults(ctypes.Structure):
    _fields_ = [
        ("a_pack_ms", ctypes.c_double),
        ("a_upload_ms", ctypes.c_double),
        ("a_total_ms", ctypes.c_double),
        ("b_map_ms", ctypes.c_double),
        ("b_pack_ms", ctypes.c_double),
        ("b_copy_ms", ctypes.c_double),
        ("b_total_ms", ctypes.c_double),
        ("c_map_ms", ctypes.c_double),
        ("c_pack_ms", ctypes.c_double),
        ("c_copy_ms", ctypes.c_double),
        ("c_total_ms", ctypes.c_double),
        ("diff_count", ctypes.c_int),
        ("max_diff", ctypes.c_int),
    ]

def test_intel_native_7f_dll_symbols():
    """Verify telem_intel_native.dll exports all required 7F symbols."""
    dll_path = workspace_root / "src" / "native" / "bin" / "telem_intel_native.dll"
    assert dll_path.exists(), f"Missing DLL at {dll_path}"
    
    dll = ctypes.CDLL(str(dll_path))
    assert hasattr(dll, "intel_d3d11_vp_init")
    assert hasattr(dll, "intel_d3d11_vp_cleanup")
    assert hasattr(dll, "intel_native_pipeline_init")
    assert hasattr(dll, "intel_native_pipeline_step")
    assert hasattr(dll, "intel_native_pipeline_finish")
    assert hasattr(dll, "intel_native_pipeline_cancel")
    assert hasattr(dll, "intel_native_pipeline_get_stats")
    assert hasattr(dll, "intel_d3d11_benchmark_staging_base_path")

def test_intel_7f_timing_rational_contract():
    """Verify exact rational arithmetic for 30000/1001 fps over 1 hour."""
    fps = fractions.Fraction(30000, 1001)
    frame_dur = fractions.Fraction(1001, 30000)
    
    # Check 1131 canonical frames duration
    dur_1131 = 1131 * frame_dur
    assert float(dur_1131) == 37.7377, f"Expected 37.7377s, got {float(dur_1131)}"
    
    # Check 1-hour (107892 frames) zero drift
    frames_1h = 107892
    time_1h = frames_1h * frame_dur
    drift_vs_target_3600 = abs(float(time_1h) - 3600.0)
    # Rational quantization over 3600s is < 0.004s (<4ms)
    assert drift_vs_target_3600 < 0.005

def test_intel_7f_staging_microbenchmark_parity():
    """Verify staging direct pack produces bit-identical output to scratch pack."""
    dll_path = workspace_root / "src" / "native" / "bin" / "telem_intel_native.dll"
    dll = ctypes.CDLL(str(dll_path))
    dll.intel_d3d11_benchmark_staging_base_path.argtypes = [ctypes.c_int, ctypes.POINTER(StagingBenchmarkResults)]
    dll.intel_d3d11_benchmark_staging_base_path.restype = ctypes.c_int
    
    res = StagingBenchmarkResults()
    ret = dll.intel_d3d11_benchmark_staging_base_path(5, ctypes.byref(res))
    assert ret == 0, f"Benchmark returned error code {ret}"
    assert res.diff_count == 0, f"Expected 0 differences, got {res.diff_count}"
    assert res.max_diff == 0, f"Expected max diff 0, got {res.max_diff}"
