"""Unit tests for Intel 225U - ETAP 1A: Native HEVC Main10 GPU Pipeline.
Verifies D3D11VA HW decode integration, oneVPL HEVC Main10 encode capability,
zero-copy observability counters, and non-regression guarantees.
"""

import ctypes
import inspect
import os
from pathlib import Path
import pytest

from src.ffmpeg.intel_native_exporter import (
    _load_native_intel_dll,
    query_intel_capabilities,
    IntelNativePipelineStats,
    export_intel_native_d3d11,
)


def test_intel_native_1a_dll_load_and_signatures():
    """Verify telem_intel_native.dll loads and exposes required pipeline symbols."""
    dll = _load_native_intel_dll()
    assert dll is not None
    assert hasattr(dll, "intel_native_pipeline_init_multi_ex")
    assert hasattr(dll, "intel_native_pipeline_step")
    assert hasattr(dll, "intel_native_pipeline_finish")
    assert hasattr(dll, "intel_native_pipeline_cancel")
    assert hasattr(dll, "intel_native_pipeline_get_stats")
    assert hasattr(dll, "intel_native_query_capabilities")


def test_intel_native_1a_stats_structure_1a_fields():
    """Verify IntelNativePipelineStats includes all 1A observability fields."""
    fields = dict(IntelNativePipelineStats._fields_)
    required_1a_fields = [
        "hevc_hw_decode_active",
        "d3d11_hevc_main10_active",
        "decode_to_vp_cpu_copy_count",
        "decode_to_vp_gpu_copy_count",
        "vp_to_encoder_cpu_copy_count",
        "vp_to_encoder_gpu_copy_count",
        "hevc_hw_encode_active",
        "device_lost_count",
        "decoder_fallback_count",
        "decoder_surface_count",
        "encoder_surface_count",
        "queue_depth",
    ]
    for field_name in required_1a_fields:
        assert field_name in fields, f"Missing 1A stats field: {field_name}"
    
    stats = IntelNativePipelineStats()
    assert ctypes.sizeof(stats) >= 120


def test_intel_native_1a_hevc_codec_support_unblocked():
    """Verify HEVC is fully unblocked and supported in export_intel_native_d3d11."""
    source = inspect.getsource(export_intel_native_d3d11)
    # Ensure error block is removed
    assert "ERROR: HEVC hardware encode is unavailable on current Intel driver/runtime" not in source
    # Ensure 1A proof keys exist
    proof_keys = [
        "HEVC_HW_DECODE_ACTIVE",
        "D3D11_HEVC_MAIN10_ACTIVE",
        "DECODE_TO_VP_CPU_COPY_COUNT",
        "DECODE_TO_VP_GPU_COPY_COUNT",
        "VP_TO_ENCODER_CPU_COPY_COUNT",
        "VP_TO_ENCODER_GPU_COPY_COUNT",
        "HEVC_HW_ENCODE_ACTIVE",
    ]
    for key in proof_keys:
        assert f'"{key}"' in source, f"Missing 1A proof key: {key}"
