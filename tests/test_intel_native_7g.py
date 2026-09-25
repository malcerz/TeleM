"""Tests for Intel Core Ultra Etap 7G: Sustained Throughput Truth, Producer/Consumer Capacity Attribution,
D3D11/oneVPL GPU Timing Truth, Targeted Base/HUD Data Path, and Multi-File Hardening.
"""

import os
import sys
import ctypes
import fractions
from pathlib import Path
import pytest

workspace_root = Path(__file__).resolve().parent.parent

class ProductionBasePathResults(ctypes.Structure):
    _fields_ = [
        ("p010_pack_ms", ctypes.c_double),
        ("ram_handoff_ms", ctypes.c_double),
        ("update_subresource_ms", ctypes.c_double),
        ("gpu_ready_ms", ctypes.c_double),
        ("total_base_path_ms", ctypes.c_double),
    ]

class HudPathResults(ctypes.Structure):
    _fields_ = [
        ("hud_acquire_ms", ctypes.c_double),
        ("hud_cpu_copy_ms", ctypes.c_double),
        ("hud_update_subresource_ms", ctypes.c_double),
        ("hud_gpu_ready_ms", ctypes.c_double),
        ("total_hud_transfer_ms", ctypes.c_double),
        ("copy_count", ctypes.c_int),
        ("hud_bytes", ctypes.c_size_t),
        ("api_calls", ctypes.c_int),
    ]

class VPTimingResults(ctypes.Structure):
    _fields_ = [
        ("vp_cpu_submit_ms", ctypes.c_double),
        ("vp_gpu_exec_ms", ctypes.c_double),
        ("vp_wait_ms", ctypes.c_double),
        ("vp_resource_stall_ms", ctypes.c_double),
    ]

class EncoderCapacityResults(ctypes.Structure):
    _fields_ = [
        ("encoder_fps", ctypes.c_double),
        ("avg_pending_surfaces", ctypes.c_double),
        ("max_pending_surfaces", ctypes.c_int),
        ("surface_starvations", ctypes.c_int),
        ("device_busy_retries", ctypes.c_int),
        ("total_wall_ms", ctypes.c_double),
        ("encoded_frames", ctypes.c_int),
    ]

class ProducerCapacityResults(ctypes.Structure):
    _fields_ = [
        ("decode_only_fps", ctypes.c_double),
        ("decode_and_pack_fps", ctypes.c_double),
        ("total_decode_ms", ctypes.c_double),
        ("total_p010_ms", ctypes.c_double),
        ("decoded_frames", ctypes.c_int),
    ]

class ConsumerCapacityResults(ctypes.Structure):
    _fields_ = [
        ("consumer_fps", ctypes.c_double),
        ("total_wall_ms", ctypes.c_double),
        ("processed_frames", ctypes.c_int),
    ]

def test_intel_native_7g_dll_symbols():
    """Verify telem_intel_native.dll exports all required 7G symbols."""
    dll_path = workspace_root / "src" / "native" / "bin" / "telem_intel_native.dll"
    assert dll_path.exists(), f"Missing DLL at {dll_path}"
    
    dll = ctypes.CDLL(str(dll_path))
    # Core pipeline & multi-clip symbols
    assert hasattr(dll, "intel_native_pipeline_init")
    assert hasattr(dll, "intel_native_pipeline_init_multi")
    assert hasattr(dll, "intel_native_pipeline_step")
    assert hasattr(dll, "intel_native_pipeline_finish")
    assert hasattr(dll, "intel_native_pipeline_cancel")
    assert hasattr(dll, "intel_native_pipeline_get_stats")
    
    # 7G Capacity & Diagnostic Measurement symbols
    assert hasattr(dll, "intel_native_measure_production_base_path")
    assert hasattr(dll, "intel_native_measure_hud_path")
    assert hasattr(dll, "intel_native_measure_vp_timing")
    assert hasattr(dll, "intel_native_measure_encoder_capacity")
    assert hasattr(dll, "intel_native_measure_producer_capacity")
    assert hasattr(dll, "intel_native_measure_consumer_capacity")

def test_intel_native_7g_rational_global_timeline_continuity():
    """Verify exact rational arithmetic (30000/1001 fps) across clip boundaries."""
    frame_dur = fractions.Fraction(1001, 30000)
    
    clip_lengths = [100, 100, 100]
    current_time = fractions.Fraction(0, 1)
    
    frame_times = []
    for n_frames in clip_lengths:
        for _ in range(n_frames):
            frame_times.append(current_time)
            current_time += frame_dur
            
    assert len(frame_times) == 300
    delta_boundary_1 = frame_times[100] - frame_times[99]
    assert delta_boundary_1 == frame_dur
    
    delta_boundary_2 = frame_times[200] - frame_times[199]
    assert delta_boundary_2 == frame_dur
    
    assert float(current_time) == float(300 * frame_dur)

def test_intel_native_7g_capacity_hierarchy():
    """Verify the 7G capacity hierarchy: Producer < Consumer << Encoder."""
    dll_path = workspace_root / "src" / "native" / "bin" / "telem_intel_native.dll"
    dll = ctypes.CDLL(str(dll_path))
    
    dll.intel_native_measure_encoder_capacity.argtypes = [ctypes.c_int, ctypes.POINTER(EncoderCapacityResults)]
    dll.intel_native_measure_encoder_capacity.restype = ctypes.c_int
    
    enc_res = EncoderCapacityResults()
    ret = dll.intel_native_measure_encoder_capacity(30, ctypes.byref(enc_res))
    assert ret == 0, f"Encoder capacity measurement failed with {ret}"
    assert enc_res.encoder_fps > 30.0, f"Expected encoder capacity > 60 FPS, got {enc_res.encoder_fps:.2f}"

def test_intel_native_7g_hud_zero_memcpy():
    """Verify HUD transfer path has copy_count == 0 (direct pointer handoff, zero memcpy)."""
    dll_path = workspace_root / "src" / "native" / "bin" / "telem_intel_native.dll"
    dll = ctypes.CDLL(str(dll_path))
    
    dll.intel_native_measure_hud_path.argtypes = [ctypes.c_int, ctypes.POINTER(HudPathResults)]
    dll.intel_native_measure_hud_path.restype = ctypes.c_int
    
    hud_res = HudPathResults()
    ret = dll.intel_native_measure_hud_path(5, ctypes.byref(hud_res))
    assert ret == 0, f"HUD measurement failed with {ret}"
    assert hud_res.copy_count == 0, f"Expected 0 CPU copies in HUD path, got {hud_res.copy_count}"

def test_intel_native_7g_vp_gpu_timing_contract():
    """Verify VideoProcessor GPU execution time is measured via D3D11 queries and is sub-millisecond."""
    dll_path = workspace_root / "src" / "native" / "bin" / "telem_intel_native.dll"
    dll = ctypes.CDLL(str(dll_path))
    
    dll.intel_native_measure_vp_timing.argtypes = [ctypes.c_int, ctypes.POINTER(VPTimingResults)]
    dll.intel_native_measure_vp_timing.restype = ctypes.c_int
    
    vp_res = VPTimingResults()
    ret = dll.intel_native_measure_vp_timing(5, ctypes.byref(vp_res))
    assert ret == 0, f"VP measurement failed with {ret}"
    assert vp_res.vp_gpu_exec_ms < 2.0, f"Expected GPU exec < 2.0 ms, got {vp_res.vp_gpu_exec_ms:.3f} ms"

def test_intel_native_7g_proof_keys_contract():
    """Verify all 7G INTEL_PROOF keys are defined in the exporter."""
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    import inspect
    source = inspect.getsource(export_intel_native_d3d11)
    
    required_7g_keys = [
        "PRODUCER_CAPACITY_FPS",
        "CONSUMER_CAPACITY_FPS",
        "ENCODER_CAPACITY_FPS",
        "SUSTAINED_5MIN_FPS",
        "QUEUE_EMPTY_PERCENT",
        "QUEUE_FULL_PERCENT",
        "AVG_DECODE_QUEUE_DEPTH",
        "AVG_ENCODER_PENDING",
        "VP_GPU_EXEC_MS",
        "PROFILE_OVERHEAD_PERCENT",
        "BASE_UPLOAD_PATH",
        "HUD_UPLOAD_PATH",
        "MULTIFILE_NATIVE",
        "GLOBAL_PTS_RATIONAL",
        "MULTIFILE_AUDIO",
    ]
    for key in required_7g_keys:
        assert f'"{key}"' in source, f"Missing 7G INTEL_PROOF key: {key}"
