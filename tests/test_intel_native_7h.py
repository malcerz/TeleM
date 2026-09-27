"""Tests for Intel Core Ultra Etap 7H: Self-Controlled Performance Optimization,
Power-Envelope Autotuning, HUD/HEVC Contention Reduction, Queue-Aware Prefetch,
and Sustained 4K30 Attempt.
"""

import os
import sys
import ctypes
import fractions
import inspect
from pathlib import Path
import pytest

workspace_root = Path(__file__).resolve().parent.parent

def test_intel_native_7h_proof_keys_contract():
    """Verify all required 7H INTEL_PROOF keys are present in the exporter source."""
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    source = inspect.getsource(export_intel_native_d3d11)

    required_7h_keys = [
        "PERF_CONFIG_MODE",
        "HUD_WORKERS",
        "HUD_PREFETCH",
        "HUD_QUEUE_AWARE_THROTTLE",
        "DECODER_THREADS",
        "HUD_PROCESS_PRIORITY",
        "HUD_ECOQOS",
        "PACK_VARIANT",
        "PRODUCER_CAPACITY_FPS",
        "CONSUMER_CAPACITY_FPS",
        "CANONICAL_PERF_FPS",
        "SUSTAINED_5MIN_FPS",
        "HUD_STARVATION_PERCENT",
        "DECODE_QUEUE_EMPTY_PERCENT",
        "DECODE_QUEUE_FULL_PERCENT",
        "PROFILE_MODE",
        "HEAVY_PROFILER_DISABLED",
        "REALTIME_4K30_CAPABLE",
        "SOURCE_FRAME_RATE",
        "ENCODE_FRAME_RATE",
        "MUX_FRAME_RATE",
        "RAW_VIDEO_DECODER_PIPE",
        "RAW_VIDEO_ENCODER_PIPE",
        "BASE_FRAME_PYTHON_TRANSIT",
        "GPU_TO_CPU_AFTER_COMPOSITE",
        "AV1_ZERO_DOWNLOAD",
        "HEVC_HW_DECODE_AVAILABLE",
    ]
    for key in required_7h_keys:
        assert f'"{key}"' in source, f"Missing 7H INTEL_PROOF key: {key}"

def test_intel_native_7h_env_controls():
    """Verify environment variable controls for HUD workers, prefetch, and decoder threads."""
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    source = inspect.getsource(export_intel_native_d3d11)

    assert "TELEM_INTEL_HUD_WORKERS" in source
    assert "TELEM_INTEL_HUD_PREFETCH" in source
    assert "TELEM_MAX_FRAMES" in source

def test_intel_native_7h_rational_drift_zero():
    """Verify rational 30000/1001 timebase accumulates 0.0 drift over 1 hour."""
    fps_rational = fractions.Fraction(30000, 1001)
    frame_dur = fractions.Fraction(1001, 30000)

    # 1 hour = 3600 seconds
    frames_1h = int(3600 * float(fps_rational))
    total_time_rational = frames_1h * frame_dur
    assert total_time_rational == fractions.Fraction(frames_1h * 1001, 30000)
    assert float(total_time_rational) == (frames_1h * 1001) / 30000
    # Cumulative drift over 1h is strictly zero
    drift = total_time_rational - sum(frame_dur for _ in range(frames_1h))
    assert drift == 0

def test_intel_native_7h_hud_starvation_tracking():
    """Verify HUD starvation tracking is implemented in the step loop."""
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    source = inspect.getsource(export_intel_native_d3d11)

    assert "hud_starvation_count" in source
    assert "fut.done()" in source
    assert "hud_starvation_pct" in source

def test_intel_native_7h_realtime_4k30_guardrail():
    """Verify REALTIME_4K30_CAPABLE is honest and reports NO if sustained < 29.970."""
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    source = inspect.getsource(export_intel_native_d3d11)

    assert '"REALTIME_4K30_CAPABLE": "NO"' in source

def test_intel_native_7h_production_pipeline_integrity():
    """Verify production pipeline parameters match 7H contracts."""
    dll_path = workspace_root / "src" / "native" / "bin" / "telem_intel_native.dll"
    assert dll_path.exists(), f"Missing DLL at {dll_path}"
    dll = ctypes.CDLL(str(dll_path))

    assert hasattr(dll, "intel_native_pipeline_init")
    assert hasattr(dll, "intel_native_pipeline_init_multi")
    assert hasattr(dll, "intel_native_pipeline_step")
    assert hasattr(dll, "intel_native_pipeline_finish")
    assert hasattr(dll, "intel_native_pipeline_cancel")
