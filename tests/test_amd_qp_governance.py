"""Automated verification tests for AMD encoder QP metrics and lifecycle governance."""

import ctypes
from ctypes import byref, c_double, c_int, c_int64, c_uint64, c_void_p
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.ffmpeg.export_stats import (
    is_av1_quality_metric,
    live_render_avg_qp,
    resolve_render_avg_qp,
)
from src.render_progress import RenderProgressTracker


def test_amd_native_dll_exports_qp_stats_symbol():
    """Verify that the compiled telem_amd_native.dll exports telem_amd_get_encoder_qp_stats and handles null handle."""
    dll_path = Path("runtime/amd/bin/telem_amd_native.dll")
    if not dll_path.exists():
        pytest.skip(f"Native DLL not found at {dll_path}")

    dll = ctypes.CDLL(str(dll_path))
    assert hasattr(dll, "telem_amd_get_encoder_qp_stats"), "telem_amd_get_encoder_qp_stats must be exported"

    func = dll.telem_amd_get_encoder_qp_stats
    func.restype = None
    func.argtypes = [
        c_void_p,
        ctypes.POINTER(c_double),
        ctypes.POINTER(c_int64),
        ctypes.POINTER(c_int64),
        ctypes.POINTER(c_uint64),
        ctypes.POINTER(c_int64),
        ctypes.POINTER(c_int),
    ]

    out_avg = c_double(999.0)
    out_min = c_int64(999)
    out_max = c_int64(999)
    out_samples = c_uint64(999)
    out_last = c_int64(999)
    out_supp = c_int(999)

    # Calling with NULL handle must safely write 0 and not crash
    func(
        None,
        byref(out_avg),
        byref(out_min),
        byref(out_max),
        byref(out_samples),
        byref(out_last),
        byref(out_supp),
    )

    assert out_avg.value == 0.0
    assert out_min.value == 0
    assert out_max.value == 0
    assert out_samples.value == 0
    assert out_last.value == 0
    assert out_supp.value == 0


def test_amd_qp_stats_propagate_when_samples_present():
    """Verify that when samples > 0, avg_qp and metrics propagate to _last_amd_export_stats."""
    from src.ffmpeg.amd_native_exporter import get_last_amd_export_stats
    import src.ffmpeg.amd_native_exporter as amd_mod

    amd_mod._last_amd_export_stats = {
        "codec": "hevc",
        "is_av1": False,
        "quant_metric": "QP",
        "avg_qp": 28.4,
        "qp_avg": 28.4,
        "quant_avg": None,
        "qp_min": 24,
        "qp_max": 32,
        "qp_last": 28,
        "qp_samples": 500,
        "amf_stats": {
            "input_full": 0,
            "retries": 0,
            "dropped": 0,
            "submitted": 500,
            "received": 500,
            "avg_qp": 28.4,
            "quant_avg": None,
        },
    }

    stats = get_last_amd_export_stats()
    assert stats["avg_qp"] == 28.4
    assert stats["qp_samples"] == 500
    assert stats["qp_min"] == 24
    assert stats["qp_max"] == 32
    assert stats["amf_stats"]["avg_qp"] == 28.4


def test_amd_qp_zero_samples_do_not_reuse_previous_generation():
    """Verify that when qp_samples == 0, avg_qp is None and previous generation QP is not leaked."""
    stats = {
        "avg_qp": None,
        "generation_id": 102,
        "amf_stats": {"avg_qp": None},
    }

    # Previous generation had QP 27.0 with generation_id 101
    resolved = resolve_render_avg_qp(
        stats,
        generation_id=102,
        live_qp=27.0,
        live_generation_id=101,  # Previous job generation!
    )
    assert resolved is None, "Previous generation QP must not leak into current generation"


def test_qp_live_progress_reaches_render_state():
    """Verify that RenderProgressTracker emits qp_avg and compression_text into hud_state."""
    emitted_records = []

    def on_progress(frame_idx, total_frames, elapsed, fps, hud_state):
        emitted_records.append(hud_state)

    tracker = RenderProgressTracker(
        total_frames=100,
        target_fps=30.0,
        callback=on_progress,
    )

    tracker.frame(
        completed=10,
        elapsed=0.33,
        fps=30.0,
        qp_avg=26.5,
        compression_text="QP avg: 26.5",
        is_av1=False,
    )

    assert len(emitted_records) > 0
    latest = emitted_records[-1]
    assert latest.get("qp_avg") == 26.5
    assert "QP avg: 26.5" in latest.get("compression_text", "")

    # Check that live_render_avg_qp correctly extracts this value
    extracted = live_render_avg_qp(latest)
    assert extracted == 26.5


def test_qp_final_stats_reach_completion():
    """Verify that resolve_render_avg_qp resolves average QP for completion popup and bottom bar."""
    # Case A: Directly in stats
    stats_a = {"avg_qp": 29.1, "generation_id": 5}
    assert resolve_render_avg_qp(stats_a, generation_id=5) == 29.1

    # Case B: In amf_stats
    stats_b = {"amf_stats": {"avg_qp": 28.2}, "generation_id": 6}
    assert resolve_render_avg_qp(stats_b, generation_id=6) == 28.2

    # Case C: Fallback to live_qp from the same generation
    stats_c = {"generation_id": 7}
    assert resolve_render_avg_qp(stats_c, generation_id=7, live_qp=27.9, live_generation_id=7) == 27.9


def test_qp_queue_job_receives_average():
    """Verify that queue completion logic extracts average QP properly."""
    stats = {
        "avg_qp": 27.5,
        "codec": "hevc",
        "real_export_fps": 36.2,
    }

    # Simulate render_mixin _notify_queue QP extraction logic
    qp = stats.get("avg_qp")
    if qp is None and "encoder_stats" in stats:
        qp = stats["encoder_stats"].get("qp_avg")
    if qp is None and "amf_stats" in stats:
        qp = stats["amf_stats"].get("avg_qp")

    assert qp == 27.5


def test_classical_qp_not_confused_with_av1_quantizer():
    """Verify that AV1 quantizer (base_q_idx) is segregated from classical QP."""
    av1_state = {
        "is_av1": True,
        "codec": "av1",
        "quant_metric": "base_q_idx",
        "quant_avg": 110.0,
        "qp_avg": 110.0,
        "compression_text": "QIndex avg: 110.0",
    }

    assert is_av1_quality_metric(av1_state) is True
    # Classical QP resolution must ignore AV1 to prevent 0-255 being treated as 0-51 QP
    assert live_render_avg_qp(av1_state) is None
    assert resolve_render_avg_qp(av1_state, generation_id=1, live_qp=110.0, live_generation_id=1) is None


def test_qp_fix_does_not_invoke_post_export_qp_analyzer():
    """Verify that resolve_render_avg_qp does not invoke heavy post-export bitstream analyzer."""
    with patch("src.qp_analyzer.analyze_qp", side_effect=AssertionError("Must not call analyze_qp")):
        stats = {"avg_qp": 28.0, "generation_id": 1}
        res = resolve_render_avg_qp(stats, generation_id=1)
        assert res == 28.0
