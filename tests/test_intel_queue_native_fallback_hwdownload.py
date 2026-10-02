"""tests/test_intel_queue_native_fallback_hwdownload.py

Regression test suite for:
A. Intel 10-bit/P010: does not generate hwdownload,format=nv12
B. Intel 8-bit/NV12: generates valid NV12
C. Multi-file 10-bit: first clip establishes contract, no default nv12 from len(input_files) > 1,
   and format mismatch across clips raises descriptive RuntimeError.
D. Consecutive queue / native: second job does not fall back to software exporter without reason.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd, _resolve_intel_cpu_format
from src.ffmpeg.streaming import _probe_intel_cpu_download_format, stream_overlay_to_ffmpeg
from src.video_helpers import find_executable


# Real test clips on disk
GOPRO_CLIP_10BIT_1 = r"C:\GoPro\2026-09-25\GX010321.MP4"
GOPRO_CLIP_10BIT_2 = r"C:\GoPro\2026-09-25\GX010322.MP4"
GOPRO_CLIP_10BIT_3 = r"C:\GoPro\2026-09-25\GX010319.MP4"


# ── Test A: Intel 10-bit/P010 does NOT generate hwdownload,format=nv12 ────────

def test_intel_10bit_p010_does_not_generate_nv12_hwdownload() -> None:
    """A 10-bit source must never generate hwdownload,format=nv12 in fallback."""
    # 1. Test strictly resolved cpu format
    cpu_fmt = _resolve_intel_cpu_format("p010le")
    assert cpu_fmt == "p010le"

    # 2. Build stream command for 10-bit Intel with software decode
    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg.exe",
        input_args=["-i", "test.mp4"],
        output_file="out.mp4",
        overlay_w=2560,
        overlay_h=1440,
        stream_w=3840,
        stream_h=2160,
        generation_fps=30.0,
        encoder="intel",
        gpu=0,
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        container_rotation=0,
        rotation_degrees=0,
        hwaccel=None,
        intel_gpu_resident=False,
        intel_gpu_compositor=False,
        intel_cpu_download_format="p010le",
        intel_cpu_software_decode=True,
        intel_codec="av1",
    )

    cmd_str = " ".join(cmd)
    assert "hwdownload,format=nv12" not in filter_complex
    assert "hwdownload,format=nv12" not in cmd_str
    assert "format=p010le" in filter_complex
    assert "-pix_fmt p010le" in cmd_str

    # 3. Build stream command for 10-bit Intel with QSV hwaccel / hwdownload
    cmd_hw, filter_complex_hw = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg.exe",
        input_args=["-hwaccel", "qsv", "-i", "test.mp4"],
        output_file="out.mp4",
        overlay_w=2560,
        overlay_h=1440,
        stream_w=3840,
        stream_h=2160,
        generation_fps=30.0,
        encoder="intel",
        gpu=0,
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        container_rotation=0,
        rotation_degrees=0,
        hwaccel="qsv",
        intel_gpu_resident=False,
        intel_gpu_compositor=False,
        intel_cpu_download_format="p010le",
        intel_cpu_software_decode=False,
        intel_codec="av1",
    )

    cmd_hw_str = " ".join(cmd_hw)
    assert "hwdownload,format=nv12" not in filter_complex_hw
    assert "hwdownload,format=nv12" not in cmd_hw_str
    assert "hwdownload,format=p010le" in filter_complex_hw
    assert "-pix_fmt p010le" in cmd_hw_str


# ── Test B: Intel 8-bit/NV12 generates valid NV12 ────────────────────────────

def test_intel_8bit_nv12_generates_valid_nv12() -> None:
    """An 8-bit source correctly generates nv12 hwdownload and encoding."""
    cpu_fmt = _resolve_intel_cpu_format("nv12")
    assert cpu_fmt == "nv12"

    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg.exe",
        input_args=["-hwaccel", "qsv", "-i", "test8.mp4"],
        output_file="out.mp4",
        overlay_w=2560,
        overlay_h=1440,
        stream_w=1920,
        stream_h=1080,
        generation_fps=30.0,
        encoder="intel",
        gpu=0,
        video_bitrate="20M",
        render_w=1920,
        render_h=1080,
        resolution_name="1080p",
        container_rotation=0,
        rotation_degrees=0,
        hwaccel="qsv",
        intel_gpu_resident=False,
        intel_gpu_compositor=False,
        intel_cpu_download_format="nv12",
        intel_cpu_software_decode=False,
        intel_codec="hevc",
    )

    cmd_str = " ".join(cmd)
    assert "hwdownload,format=nv12" in filter_complex
    assert "-pix_fmt nv12" in cmd_str
    assert "p010le" not in filter_complex


# ── Test C: Multi-file 10-bit probing and consistency contract ───────────────

def test_multifile_10bit_probes_first_clip_and_validates_subsequent() -> None:
    """Multi-file 10-bit sequences must probe the first clip, never default to nv12,

    and raise an explicit RuntimeError if clips have mismatched pixel formats.
    """
    ffmpeg_exe = find_executable("ffmpeg") or "ffmpeg.exe"

    if Path(GOPRO_CLIP_10BIT_1).exists() and Path(GOPRO_CLIP_10BIT_2).exists():
        # Real multi-file 10-bit clips
        clips = [GOPRO_CLIP_10BIT_1, GOPRO_CLIP_10BIT_2]
        fmt = _probe_intel_cpu_download_format(clips, ffmpeg_exe)
        assert fmt == "p010le", f"Expected 'p010le' for 10-bit GoPro clips, got '{fmt}'"

    # Mocked multi-file: test consistency across clips
    def mock_subprocess_run(cmd, *args, **kwargs):
        clip = cmd[-1]
        mock_res = MagicMock()
        mock_res.returncode = 0
        if "clip10_a" in clip or "clip10_b" in clip:
            mock_res.stdout = "yuv420p10le\n"
        elif "clip8" in clip:
            mock_res.stdout = "yuv420p\n"
        else:
            mock_res.stdout = "unknown_pix_fmt\n"
        return mock_res

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        # 1. Both clips 10-bit -> returns p010le
        res = _probe_intel_cpu_download_format(["clip10_a.mp4", "clip10_b.mp4"], ffmpeg_exe)
        assert res == "p010le"

        # 2. Both clips 8-bit -> returns nv12
        res8 = _probe_intel_cpu_download_format(["clip8.mp4"], ffmpeg_exe)
        assert res8 == "nv12"

        # 3. Clip 1 is 10-bit but Clip 2 is 8-bit -> raises RuntimeError describing mismatch
        with pytest.raises(RuntimeError, match="Multi-file clip format mismatch"):
            _probe_intel_cpu_download_format(["clip10_a.mp4", "clip8.mp4"], ffmpeg_exe)

        # 4. Unknown format -> raises RuntimeError, never guesses nv12
        with pytest.raises(RuntimeError, match="Unsupported or unrecognised pixel format"):
            _probe_intel_cpu_download_format(["unknown.mp4"], ffmpeg_exe)


# ── Test D1: Consecutive dispatch logic and structured logging contract ──────

def test_consecutive_intel_queue_dispatch_contract() -> None:
    """Verify structured log emission and that successful native jobs never fall back."""
    from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

    log_buffer = io.StringIO()

    mock_native_calls = []

    def mock_native_exporter(**kwargs):
        mock_native_calls.append(kwargs)
        return True  # Native success

    common_args = dict(
        ffmpeg_exe="ffmpeg.exe",
        duration_s=1.0,
        start_dt_utc=None,
        tz_offset_hours=2,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path=None,
        layout={"indicators": {}},
        field_samples={},
        encoder="intel",
    )

    mock_res = MagicMock()
    mock_res.selected_codec = "hevc"
    mock_res.adapter_index = 0
    mock_res.adapters = [{"index": 0}]

    with patch("src.ffmpeg.intel_native_exporter.export_intel_native_d3d11", side_effect=mock_native_exporter), \
         patch("src.ffmpeg.intel_native_exporter.is_intel_native_available", return_value=(True, "available")), \
         patch("src.ffmpeg.streaming.resolve_intel_force", return_value=mock_res), \
         patch("src.ffmpeg.streaming._probe_intel_cpu_download_format", return_value="p010le"), \
         contextlib.redirect_stdout(log_buffer):

        # Job 1
        res1 = stream_overlay_to_ffmpeg(
            input_files=["clip1.mp4"],
            output_file="out1.mp4",
            **common_args
        )
        assert res1 > 0
        assert len(mock_native_calls) == 1

        # Job 2 (multi-file)
        res2 = stream_overlay_to_ffmpeg(
            input_files=["clip2_a.mp4", "clip2_b.mp4"],
            output_file="out2.mp4",
            **common_args
        )
        assert res2 > 0
        assert len(mock_native_calls) == 2

    logs = log_buffer.getvalue()

    # Verify structured logs are present
    assert "[INTEL_JOB_START]" in logs
    assert "[INTEL_NATIVE_REQUESTED] requested=YES" in logs
    assert "[INTEL_NATIVE_AVAILABLE] available=YES" in logs
    assert "[INTEL_NATIVE_ENTERED] entered=YES" in logs
    assert "[INTEL_NATIVE_RESULT] success=YES" in logs
    assert "[INTEL_FFMPEG_FALLBACK_ENTERED]" not in logs


# ── Test D2: Fallback records root cause if native fails ──────────────────────

def test_intel_fallback_records_root_cause_on_failure() -> None:
    """If native export fails or raises, root cause is logged and fallback is entered."""
    from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

    log_buffer = io.StringIO()

    common_args = dict(
        ffmpeg_exe="ffmpeg.exe",
        duration_s=0.1,
        start_dt_utc=None,
        tz_offset_hours=2,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path=None,
        layout={"indicators": {}},
        field_samples={},
        encoder="intel",
    )

    mock_res = MagicMock()
    mock_res.selected_codec = "hevc"
    mock_res.adapter_index = 0
    mock_res.adapters = [{"index": 0}]

    with patch("src.ffmpeg.intel_native_exporter.export_intel_native_d3d11", return_value=False), \
         patch("src.ffmpeg.intel_native_exporter.is_intel_native_available", return_value=(True, "available")), \
         patch("src.ffmpeg.streaming.resolve_intel_force", return_value=mock_res), \
         patch("src.ffmpeg.streaming._probe_intel_cpu_download_format", return_value="p010le"), \
         patch("src.ffmpeg.streaming.subprocess.Popen") as mock_popen, \
         contextlib.redirect_stdout(log_buffer):

        # Mock ffmpeg process for the fallback
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"")
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        try:
            stream_overlay_to_ffmpeg(
                input_files=["clip1.mp4"],
                output_file="out1.mp4",
                **common_args
            )
        except Exception:
            pass

    logs = log_buffer.getvalue()
    assert "[INTEL_NATIVE_RESULT] success=NO" in logs
    assert "[INTEL_NATIVE_FALLBACK_REASON] export_intel_native_d3d11 returned False" in logs
    assert "[INTEL_FFMPEG_FALLBACK_ENTERED]" in logs
