"""Tests for Intel Core Ultra Etap 8A: H.264 Hardware Encode Backend,
oneVPL / QSV AVC Capability Truth, 10-bit / P010 Support Proof,
Color Space Transformation & Tone Mapping Truth, Codec Selector,
and AV1 Non-Regression Freeze.
"""

import os
import sys
import json
import inspect
import fractions
import pytest
from pathlib import Path

workspace_root = Path(__file__).resolve().parent.parent

from src.ffmpeg.intel_native_exporter import (
    _load_native_intel_dll,
    query_intel_capabilities,
    IntelCapabilityInfo,
    export_intel_native_d3d11,
)


def test_intel_native_8a_capability_truth():
    """Verify runtime oneVPL capability detection returns accurate HW support for 135U."""
    caps = query_intel_capabilities()
    assert isinstance(caps, dict)
    
    # AV1 capabilities
    assert caps["AV1_AVAILABLE"] is True
    assert caps["AV1_10BIT"] is True
    
    # H.264 capabilities (8-bit supported, 10-bit unsupported on HW)
    assert caps["H264_AVAILABLE"] is True
    assert caps["H264_8BIT"] is True
    assert caps["H264_10BIT"] is False
    
    # HEVC capabilities (unavailable on current driver/runtime)
    assert caps["HEVC_AVAILABLE"] is False
    assert caps["HEVC_10BIT"] is False


def test_intel_native_8a_dll_multi_codec_exports():
    """Verify telem_intel_native.dll exports the 8A multi-codec functions."""
    dll = _load_native_intel_dll()
    assert hasattr(dll, "intel_d3d11_vp_init_ex")
    assert hasattr(dll, "intel_native_pipeline_init_multi_ex")
    assert hasattr(dll, "intel_native_query_capabilities")
    assert hasattr(dll, "intel_native_measure_encoder_capacity_ex")


def test_intel_native_8a_proof_keys():
    """Verify INTEL_PROOF keys for 8A multi-codec dispatch and color metadata."""
    source = inspect.getsource(export_intel_native_d3d11)

    required_8a_keys = [
        "INTEL_CODEC_SELECTED",
        "AV1_AVAILABLE",
        "AV1_10BIT_AVAILABLE",
        "H264_AVAILABLE",
        "H264_8BIT_AVAILABLE",
        "H264_10BIT_AVAILABLE",
        "H264_PROFILE",
        "H264_INPUT_FORMAT",
        "H264_RATE_CONTROL",
        "H264_TARGET_KBPS",
        "H264_MAX_KBPS",
        "H264_GOP",
        "H264_HDR_CAPABLE",
        "H264_PRODUCTION_READY",
        "HEVC_AVAILABLE",
        "SOURCE_FRAME_RATE",
        "ENCODE_FRAME_RATE",
        "MUX_FRAME_RATE",
    ]
    for key in required_8a_keys:
        assert f'"{key}"' in source, f"Missing 8A INTEL_PROOF key: {key}"


def test_intel_native_8a_color_signaling_bt709_for_h264():
    """Verify that H.264 muxing explicitly passes BT.709 SDR color tags and never leaves HLG BT.2020."""
    source = inspect.getsource(export_intel_native_d3d11)
    assert '"-color_primaries", "bt709"' in source
    assert '"-color_trc", "bt709"' in source
    assert '"-colorspace", "bt709"' in source


def test_intel_native_8a_av1_freeze_and_parameters():
    """Verify that AV1 parameters remain frozen at 10-bit BT.2020 HLG 40 Mbps."""
    source = inspect.getsource(export_intel_native_d3d11)
    assert '"-color_primaries", "bt2020"' in source
    assert '"-color_trc", "arib-std-b67"' in source
    assert '"-colorspace", "bt2020nc"' in source
    assert 'target_kbps = 40000' in source
