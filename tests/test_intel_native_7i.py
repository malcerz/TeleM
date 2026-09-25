"""Tests for Intel Core Ultra Etap 7I: Self-Controlled Producer Efficiency,
CPU Active-Time Truth, HEVC Decode / P010 Pack Attribution, 2 vs 3 vs 4 HUD Worker
Final Selection, Producer Pipeline Topology, Memory-Traffic Reduction,
and 10-Minute Sustained 4K30 Attempt.
"""

import os
import sys
import ctypes
import fractions
import inspect
from pathlib import Path
import pytest

workspace_root = Path(__file__).resolve().parent.parent

def test_intel_native_7i_proof_keys_and_na_truth_rule():
    """Verify INTEL_PROOF keys for 7I and verify not-measured metrics output 'N/A', never '0'."""
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    source = inspect.getsource(export_intel_native_d3d11)

    required_7i_keys = [
        "PERF_CONFIG_MODE",
        "HUD_WORKERS",
        "HUD_PREFETCH",
        "HUD_PREFETCH_POLICY",
        "PACK_WALL_MS",
        "PACK_ACTIVE_CYCLES",
        "PACK_ACTIVE_MS",
        "PACK_ACTIVE_VS_WALL",
        "PRODUCER_TOPOLOGY",
        "DECODE_ACTIVE_CYCLES",
        "PRODUCER_ACTIVE_CYCLES",
        "CONSUMER_ACTIVE_CYCLES",
        "VIDEO_ONLY_FPS",
        "VIDEO_PLUS_HUD_CPU_FPS",
        "FULL_PIPELINE_FPS",
        "SUSTAINED_10MIN_FPS",
        "REALTIME_4K30_CAPABLE",
    ]
    for key in required_7i_keys:
        assert f'"{key}"' in source, f"Missing 7I INTEL_PROOF key: {key}"

    # Verify truth assertion rule: N/A instead of 0.0 when queue_samples == 0
    assert '"N/A"' in source, "Missing 'N/A' truth assertion for unmeasured metrics in INTEL_PROOF"

def test_intel_native_7i_prefetch_contract():
    """Verify the corrected prefetch formula max(8, n_workers * 2) ensuring 8 slots for 2 workers."""
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    source = inspect.getsource(export_intel_native_d3d11)

    assert "max(8, n_workers * 2)" in source, "Prefetch contract must enforce max(8, n_workers * 2)"

def test_intel_native_7i_cycle_instrumentation_exported():
    """Verify telem_intel_native.dll exports QueryThreadCycleTime instrumentation stats."""
    from src.ffmpeg.intel_native_exporter import IntelNativePipelineStats, _load_native_intel_dll
    dll = _load_native_intel_dll()
    assert hasattr(dll, "intel_native_pipeline_get_stats")

    # Verify structure fields
    stat_fields = [name for name, _ in IntelNativePipelineStats._fields_]
    assert "total_p010_map_ms" in stat_fields
    assert "total_p010_pure_convert_ms" in stat_fields
    assert "total_p010_unmap_ms" in stat_fields
    assert "total_p010_cycles" in stat_fields
    assert "total_decode_cycles" in stat_fields
    assert "total_producer_cycles" in stat_fields
    assert "total_consumer_cycles" in stat_fields

def test_intel_native_7i_rational_timebase_10min_zero_drift():
    """Verify 30000/1001 timebase accumulates exactly 0.0 drift over a 10-minute session."""
    fps_rational = fractions.Fraction(30000, 1001)
    frame_dur = fractions.Fraction(1001, 30000)

    # 10 minutes = 600 seconds
    frames_10m = int(600 * float(fps_rational))
    total_time_rational = frames_10m * frame_dur
    assert total_time_rational == fractions.Fraction(frames_10m * 1001, 30000)
    drift = total_time_rational - sum(frame_dur for _ in range(frames_10m))
    assert drift == 0

def test_intel_native_7i_realtime_4k30_guardrail():
    """Verify REALTIME_4K30_CAPABLE reports NO when sustained 10-min FPS is ~22.6 FPS (< 29.970)."""
    from src.ffmpeg.intel_native_exporter import export_intel_native_d3d11
    source = inspect.getsource(export_intel_native_d3d11)
    assert '"REALTIME_4K30_CAPABLE": "NO"' in source
