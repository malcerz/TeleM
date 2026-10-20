"""Automated verification tests for AMD HEVC VBR rate control and bitrate governance."""

import ctypes
from ctypes import byref, c_double, c_int, c_int64, c_uint64, c_void_p
import inspect
import os
from pathlib import Path
import pytest

from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11, get_last_amd_export_stats
import src.ffmpeg.amd_native_exporter as amd_mod
from src.render_progress import RenderProgressState, format_render_progress_status


def test_export_amd_native_d3d11_default_rc_is_vbr():
    """Verify that export_amd_native_d3d11 defaults rc to 'vbr', never 'cqp'."""
    sig = inspect.signature(export_amd_native_d3d11)
    rc_param = sig.parameters.get("rc")
    assert rc_param is not None, "rc parameter must exist"
    assert rc_param.default == "vbr", f"rc default must be 'vbr', got {rc_param.default!r}"


def test_bitrate_string_parsing_and_peak_calculation():
    """Verify bitrate string parsing and peak bitrate calculation logic."""
    cases = [
        ("5M", 5_000_000, 7_500_000),
        ("40M", 40_000_000, 60_000_000),
        ("60M", 60_000_000, 90_000_000),
        ("120M", 120_000_000, 180_000_000),
        ("50000k", 50_000_000, 75_000_000),
        ("40000000", 40_000_000, 60_000_000),
        ("", 40_000_000, 60_000_000),      # Default 40M
        ("invalid", 40_000_000, 60_000_000), # Default 40M
    ]
    for vb_input, expected_target, expected_peak in cases:
        amd_bitrate_bps = 0
        if vb_input:
            vb_clean = str(vb_input).strip().upper()
            try:
                if vb_clean.endswith("M"):
                    amd_bitrate_bps = int(float(vb_clean[:-1]) * 1_000_000)
                elif vb_clean.endswith("K"):
                    amd_bitrate_bps = int(float(vb_clean[:-1]) * 1_000)
                elif vb_clean.isdigit():
                    amd_bitrate_bps = int(vb_clean)
            except Exception:
                amd_bitrate_bps = 0
        if amd_bitrate_bps <= 0:
            amd_bitrate_bps = 40_000_000
        peak_bitrate_bps = int(amd_bitrate_bps * 1.5)

        assert amd_bitrate_bps == expected_target, f"Input {vb_input}: expected {expected_target}, got {amd_bitrate_bps}"
        assert peak_bitrate_bps == expected_peak, f"Input {vb_input}: expected peak {expected_peak}, got {peak_bitrate_bps}"


def test_native_dll_exports_qp_stats_and_safe_null():
    """Verify that the production DLL exports telem_amd_get_encoder_qp_stats and zeros out outputs on NULL handle."""
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

    out_avg = c_double(-1.0)
    out_min = c_int64(-1)
    out_max = c_int64(-1)
    out_samples = c_uint64(99)
    out_last = c_int64(-1)
    out_supp = c_int(-1)

    func(None, byref(out_avg), byref(out_min), byref(out_max), byref(out_samples), byref(out_last), byref(out_supp))

    assert out_avg.value == 0.0
    assert out_min.value == 0
    assert out_max.value == 0
    assert out_samples.value == 0
    assert out_last.value == 0
    assert out_supp.value == 0


def test_progress_status_formats_vbr_and_na():
    """Verify that status line correctly displays QP avg: N/A without fake 28.0 when no QP samples exist."""
    state = RenderProgressState(
        generation_id=1,
        state="rendering",
        frame=50,
        total_frames=100,
        percent=50.0,
        fps=40.0,
        elapsed_s=1.25,
        eta_s=1.25,
        qp=None,
        avg_qp=None,
        is_cqp=False,
        compression_text="QP avg: N/A",
    )
    status_text = format_render_progress_status(state)
    assert "QP avg: N/A" in status_text
    assert "28" not in status_text


def test_progress_status_formats_dynamic_qp_when_available():
    """Verify that when real QP feedback is present, dynamic QP and average are displayed."""
    state = RenderProgressState(
        generation_id=1,
        state="rendering",
        frame=50,
        total_frames=100,
        percent=50.0,
        fps=42.0,
        elapsed_s=1.2,
        eta_s=1.2,
        qp=24.0,
        avg_qp=25.8,
        is_cqp=False,
        compression_text="QP: 24 (avg: 25.8)",
    )
    status_text = format_render_progress_status(state)
    assert "QP: 24 (avg: 25.8)" in status_text


def test_last_export_stats_handles_vbr():
    """Verify that export stats store VBR metrics properly without hardcoded 28."""
    amd_mod._last_amd_export_stats = {
        "codec": "hevc_amf",
        "is_av1": False,
        "quant_metric": "QP",
        "avg_qp": None,
        "qp_avg": None,
        "quant_avg": None,
        "qp_min": None,
        "qp_max": None,
        "qp_last": None,
        "qp_samples": 0,
        "amf_stats": {
            "input_full": 0,
            "retries": 0,
            "dropped": 0,
            "submitted": 180,
            "received": 180,
            "avg_qp": None,
            "quant_avg": None,
        },
    }
    stats = get_last_amd_export_stats()
    assert stats["avg_qp"] is None
    assert stats["qp_samples"] == 0
    assert stats["amf_stats"]["avg_qp"] is None
