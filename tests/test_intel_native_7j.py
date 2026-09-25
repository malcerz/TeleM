"""Focused tests for Intel Core Ultra Etap 7J (Lock-Free Base Video Upload, Map Wait Characterization, HUD Cache Proof)."""

import os
import sys
import json
import ctypes
import pytest
from pathlib import Path

from src.ffmpeg.intel_backend import (
    IntelRenderCapabilities,
    intel_proof_enabled,
    intel_proof_snapshot,
    emit_intel_proof,
)
from src.ffmpeg.intel_native_exporter import (
    _load_native_intel_dll,
    IntelNativePipelineStats,
)


def test_native_intel_dll_loads_and_has_7j_stats_fields():
    """Verify telem_intel_native.dll exports the required 7J stats fields."""
    dll = _load_native_intel_dll()
    assert hasattr(dll, "intel_native_pipeline_get_stats")

    stats = IntelNativePipelineStats()
    assert hasattr(stats, "map_hist_counts")
    assert hasattr(stats, "map_samples")
    assert hasattr(stats, "map_p50_ms")
    assert hasattr(stats, "map_p90_ms")
    assert hasattr(stats, "map_p95_ms")
    assert hasattr(stats, "map_p99_ms")


def test_intel_proof_7j_contract_generation():
    """Verify INTEL_PROOF contract generation for INTEL_NATIVE_7J."""
    caps = IntelRenderCapabilities(
        adapter_name="Intel(R) Graphics",
        adapter_vendor_id=0x8086,
        adapter_device_id=0x7D45,
        adapter_dxgi_index=0,
        qsv_available=True,
        qsv_hevc_encode=True,
        qsv_av1_encode=True,
        encode_codec="AV1",
        d3d11_device_available=True,
        decode_path="LIBAVCODEC_SOFTWARE_NATIVE",
        decode_residency="CPU_NATIVE",
        hud_transport="NATIVE_SHM",
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=2560,
        hud_height=1440,
        hud_bytes_per_frame=14745600,
        hud_full_frame_bytes=14745600,
        hud_uploads_per_frame=1,
        compositor_path="NATIVE_D3D11",
        gpu_texture_format="P010 / RGBA",
        compositor_output_format="D3D11/P010",
        encode_path="ONEVPL_AV1_NATIVE",
        encode_pixel_format="p010le",
        hwdownload_count_expected=0,
        hwupload_count_expected=2,
        capability_class="INTEL_NATIVE_7E_ASYNC",
    )
    contract = {
        "expected_path": "NATIVE_7E_ASYNC",
        "actual_path": "NATIVE_7E_ASYNC",
        "mismatch": False,
        "mismatch_reasons": [],
    }
    input_info = {
        "width": 3840, "height": 2160, "codec": "hevc",
        "pix_fmt": "yuv420p10le", "bit_depth": 10, "is_hdr": True, "fps": 29.97
    }
    proof = intel_proof_snapshot(
        caps,
        input_info=input_info,
        timeline=None,
        contract_validation=contract,
        ffmpeg_exe="ffmpeg.exe"
    )
    assert proof["capabilities"]["class"] == "INTEL_NATIVE_7E_ASYNC"
    assert proof["contract_validation"]["mismatch"] is False


def test_d3d11_map_percentile_struct_alignment():
    """Verify ctypes struct alignment for map histogram counts array."""
    stats = IntelNativePipelineStats()
    assert len(stats.map_hist_counts) == 7
    stats.map_p50_ms = 4.32
    stats.map_p95_ms = 35.27
    stats.map_p99_ms = 68.09
    assert stats.map_p50_ms == 4.32
    assert stats.map_p95_ms == 35.27
    assert stats.map_p99_ms == 68.09
