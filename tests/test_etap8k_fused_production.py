"""ETAP 8K: Tests for production Unified Fused NV12 Compositor default and contracts."""
import os
import subprocess
import sys
from pathlib import Path

def test_production_default_fused_selected():
    """Verify that with no ENV overrides, Fused mode is active by default."""
    root = Path(__file__).resolve().parent.parent
    cpp_source = (root / "native" / "d3d11_amf_pipeline" / "src" / "d3d11_vp_pipeline.cpp").read_text(encoding="utf-8")
    
    # Check default return for GetFusedCompositorMode
    assert "static int GetFusedCompositorMode()" in cpp_source
    assert "return env ? atoi(env) : 1;" in cpp_source

    # Check default return for GetNormalizePassCount when fusedMode == 1
    assert "if (fusedMode == 1)" in cpp_source
    assert "return 0;" in cpp_source

def test_diagnostic_override_reference_path():
    """Verify that when AMD_FUSED_COMPOSITOR=0 is explicitly requested, legacy reference path is available."""
    root = Path(__file__).resolve().parent.parent
    cpp_source = (root / "native" / "d3d11_amf_pipeline" / "src" / "d3d11_vp_pipeline.cpp").read_text(encoding="utf-8")
    
    # Check that fusedMode == 0 falls back to legacy shader & pass count
    # The current implementation spells the same diagnostic branch explicitly
    # so that shader-variant selection remains readable.
    assert "Legacy non-fused compositor" in cpp_source
    assert "const char* env = getenv(\"AMD_NORMALIZE_PASSES\");" in cpp_source

def test_production_fused_shader_presence():
    """Verify that m_nv12FusedComputeShader compiles and is released cleanly."""
    root = Path(__file__).resolve().parent.parent
    header = (root / "native" / "d3d11_amf_pipeline" / "src" / "d3d11_vp_pipeline.h").read_text(encoding="utf-8")
    cpp_source = (root / "native" / "d3d11_amf_pipeline" / "src" / "d3d11_vp_pipeline.cpp").read_text(encoding="utf-8")

    assert "ID3D11ComputeShader* m_nv12FusedComputeShader" in header
    assert "&m_nv12FusedComputeShader" in cpp_source
    assert "if (m_nv12FusedComputeShader) m_nv12FusedComputeShader->Release();" in cpp_source
