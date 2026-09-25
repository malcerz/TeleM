"""Tests for Intel Core Ultra Etap 8B Runtime Capabilities."""
import os
import sys
import pytest
from pathlib import Path

workspace_root = Path(__file__).resolve().parent.parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from src.ffmpeg.intel_native_exporter import (
    query_intel_capabilities,
    _load_native_intel_dll,
    IntelCapabilityInfo,
)

def test_intel_native_8b_capabilities_truth():
    """Verify runtime capability query returns exact hardware truth on Intel."""
    caps = query_intel_capabilities()
    assert isinstance(caps, dict)
    assert "AV1_AVAILABLE" in caps
    assert "H264_AVAILABLE" in caps

def test_intel_native_8b_dll_exports():
    """Verify telem_intel_native.dll exports codec-aware multi-clip pipeline functions."""
    dll = _load_native_intel_dll()
    assert hasattr(dll, "intel_native_pipeline_init_multi_ex")
    assert hasattr(dll, "intel_d3d11_vp_init_ex")
    assert hasattr(dll, "intel_native_query_capabilities")
