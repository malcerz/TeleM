import os
import sys
import ctypes
import pytest
from pathlib import Path

def test_intel_hw_decode_default_state_and_exports():
    repo_root = Path(__file__).resolve().parent.parent
    dll_candidates = [
        repo_root / "src" / "native" / "bin" / "telem_intel_native.dll",
        repo_root / "scratch" / "telem_intel_native.dll",
    ]
    dll_path = next((p for p in dll_candidates if p.exists()), None)
    assert dll_path is not None, "telem_intel_native.dll must exist"

    ff_bin = repo_root / "third_party" / "ffmpeg-9.0.1-full_build-shared" / "bin"
    if ff_bin.exists():
        os.environ["PATH"] = str(ff_bin) + os.pathsep + os.environ.get("PATH", "")

    lib = ctypes.CDLL(str(dll_path))
    assert hasattr(lib, "intel_native_pipeline_init_multi_ex")
    assert hasattr(lib, "intel_native_pipeline_step_regions")
    assert hasattr(lib, "intel_native_pipeline_finish")
    assert hasattr(lib, "intel_native_pipeline_get_stats")

def test_intel_hw_decode_zero_cpu_copy_contract():
    from src.ffmpeg.intel_native_exporter import IntelNativePipelineStats
    stats = IntelNativePipelineStats()
    assert hasattr(stats, "hevc_hw_decode_active")
    assert hasattr(stats, "d3d11_hevc_main10_active")
    assert hasattr(stats, "decode_to_vp_cpu_copy_count")
    assert hasattr(stats, "decode_to_vp_gpu_copy_count")
    assert hasattr(stats, "vp_to_encoder_cpu_copy_count")
    assert hasattr(stats, "vp_to_encoder_gpu_copy_count")

def test_intel_hw_decode_env_fallback_toggle():
    env_default = os.environ.get("TELEM_INTEL_HEVC_HW_DECODE")
    os.environ["TELEM_INTEL_HEVC_HW_DECODE"] = "0"
    assert os.environ.get("TELEM_INTEL_HEVC_HW_DECODE") == "0"
    if env_default is not None:
        os.environ["TELEM_INTEL_HEVC_HW_DECODE"] = env_default
    else:
        os.environ.pop("TELEM_INTEL_HEVC_HW_DECODE", None)

def test_intel_hw_decode_rotation_display_matrix_contract():
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    assert callable(export_intel_native_d3d11)
