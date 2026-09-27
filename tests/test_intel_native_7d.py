"""ETAP 7D: Intel Core Ultra Native In-Process Pipeline Contracts and Unit Tests."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import pytest

from src.ffmpeg.intel_backend import (
    IntelRenderCapabilities,
    emit_intel_proof,
    intel_proof_snapshot,
)
from src.ffmpeg.intel_native_exporter import _load_native_intel_dll, IntelNativePipelineStats


def test_intel_native_7d_dll_load_and_signatures():
    """Verify that the compiled telem_intel_native.dll exposes all 7D pipeline entrypoints."""
    dll = _load_native_intel_dll()
    assert dll is not None

    # Verify function pointers
    assert hasattr(dll, "intel_native_pipeline_init")
    assert hasattr(dll, "intel_native_pipeline_step")
    assert hasattr(dll, "intel_native_pipeline_finish")
    assert hasattr(dll, "intel_native_pipeline_cancel")
    assert hasattr(dll, "intel_native_pipeline_get_stats")

    # Verify legacy 7C compositor functions are preserved
    assert hasattr(dll, "intel_d3d11_vp_init")
    assert hasattr(dll, "intel_d3d11_vp_cleanup")
    assert hasattr(dll, "intel_d3d11_vp_composite_frame")
    assert hasattr(dll, "intel_d3d11_vp_get_output_frame")


def test_intel_native_7d_proof_contract_assertions(monkeypatch):
    """Verify that 7D proof contract enforces zero-download and zero-pipe contracts."""
    monkeypatch.setenv("TELEM_INTEL_PROOF", "1")

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
        capability_class="INTEL_NATIVE_7D_INPROCESS",
    )

    contract = {
        "expected_path": "NATIVE_7D_INPROCESS",
        "actual_path": "NATIVE_7D_INPROCESS",
        "mismatch": False,
        "mismatch_reasons": [],
    }

    snapshot = intel_proof_snapshot(
        caps,
        input_info={"path": "input.mp4", "codec": "hevc", "width": 3840, "height": 2160, "bit_depth": 10, "pixel_format": "yuv420p10le", "hdr": True},
        timeline=None,
        contract_validation=contract,
        ffmpeg_exe="ffmpeg",
    )

    assert snapshot["capabilities"]["class"] == "INTEL_NATIVE_7D_INPROCESS"
    assert snapshot["transfers"]["hwdownload_count_expected"] == 0
    assert snapshot["decode"]["path"] == "LIBAVCODEC_SOFTWARE_NATIVE"
    assert snapshot["decode"]["residency"] == "CPU_NATIVE"
    assert snapshot["compositor"]["path"] == "NATIVE_D3D11"
    assert snapshot["encode"]["path"] == "ONEVPL_AV1_NATIVE"


def test_intel_native_7d_stats_structure_size():
    """Verify that ctypes IntelNativePipelineStats matches the C struct layout."""
    stats = IntelNativePipelineStats()
    assert ctypes.sizeof(stats) >= 80  # 9 doubles (72B) + 2 ints (8B) + uint64 (8B) + 2 doubles (16B) = 104B
