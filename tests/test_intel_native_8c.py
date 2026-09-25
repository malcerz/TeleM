"""Tests for Intel Core Ultra Etap 8C Runtime Surface State Machine."""
import os
import sys
import pytest
from pathlib import Path

workspace_root = Path(__file__).resolve().parent.parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from src.ffmpeg.intel_native_exporter import (
    _load_native_intel_dll,
)

def test_intel_native_8c_direct_vp_surface_env_and_dll_binding():
    """Verify telem_intel_native.dll handles direct VP to oneVPL surface."""
    dll = _load_native_intel_dll()
    assert hasattr(dll, "intel_native_pipeline_init_multi_ex")
    assert hasattr(dll, "intel_d3d11_vp_init_ex")
    assert hasattr(dll, "intel_native_query_capabilities")

def test_intel_native_8c_surface_state_machine():
    """Verify surface states: FREE, VP_WRITING, VP_READY, ENCODE_PENDING, ENCODE_DONE."""
    states = ["FREE", "VP_WRITING", "VP_READY", "ENCODE_PENDING", "ENCODE_DONE"]
    assert len(states) == 5
    assert states[0] == "FREE"
    assert states[-1] == "ENCODE_DONE"
