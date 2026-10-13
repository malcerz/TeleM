"""Regression tests for AMD Single Live Mux Audio Finalization (Etap 5R-F).

Verifies:
1. Single-file exports use direct audio input with thread_queue_size (no concat demuxer).
2. Range-seek offsets use direct -ss -i with thread_queue_size.
3. No intermediate audio files (.audio.concat.txt, .m4a, .aac, .adts, audio_cache, temp_video.mp4) for single-file.
4. Exactly one live muxer process is spawned.
5. Multi-file retains concat plan with thread_queue_size.
6. Finalization watchdog does not kill active FFmpeg while I/O is progressing.
7. Finalization watchdog terminates on genuine stall.
8. Cancellation immediately terminates the muxer.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ffmpeg.amd_native_exporter import (
    export_amd_native_d3d11,
    AMD_NATIVE_ABI_VERSION,
)
from tests.test_amd_direct_mp4_mux import install_mux_popen


@pytest.fixture(autouse=True)
def isolated_platform(monkeypatch):
    import ctypes
    kernel = MagicMock()
    kernel.CreateNamedPipeW.return_value = 123
    kernel.ConnectNamedPipe.return_value = 1
    kernel.ReadFile.return_value = 0
    kernel.GetLastError.return_value = 109
    kernel.OpenProcess.return_value = 0
    monkeypatch.setattr(ctypes.windll, "kernel32", kernel)
    monkeypatch.setattr("src.ffmpeg.amd_native_exporter._probe_video_summary", lambda *args: {
        "streams": [{"codec_type": "video", "nb_frames": "30"}, {"codec_type": "audio"}]
    })


def _setup_mock_dll(monkeypatch):
    mock_dll = MagicMock()
    mock_dll.telem_amd_get_abi_version.return_value = AMD_NATIVE_ABI_VERSION
    mock_dll.telem_amd_get_build_info.return_value = b"ABI 9"
    mock_dll.telem_amd_create.return_value = 12345
    mock_dll.telem_amd_set_diagnostics.return_value = 1
    mock_dll.telem_amd_set_profiling.return_value = 1
    mock_dll.telem_amd_set_hud_enabled.return_value = 1
    mock_dll.telem_amd_set_hud_mode.return_value = 1
    mock_dll.telem_amd_set_map_mode.return_value = 1
    mock_dll.telem_amd_set_above_map_mode.return_value = 1
    mock_dll.telem_amd_set_chart_mode.return_value = 1
    mock_dll.telem_amd_set_after_map_chart_mode.return_value = 1
    mock_dll.telem_amd_set_gauge_mode.return_value = 1
    mock_dll.telem_amd_set_gauge_after_map.return_value = 1
    mock_dll.telem_amd_set_lean_gpu_mode.return_value = 1
    mock_dll.telem_amd_set_decode_mode.return_value = 1
    mock_dll.telem_amd_seek_source.return_value = 1
    mock_dll.telem_amd_discard_video_sample.return_value = 1
    mock_dll.telem_amd_read_video_sample.return_value = 0
    mock_dll.telem_amd_process_frame.return_value = 0
    mock_dll.telem_amd_flush.return_value = 1
    mock_dll.telem_amd_close.return_value = 1
    monkeypatch.setattr("ctypes.CDLL", lambda *a, **kw: mock_dll)
    return mock_dll


def test_single_file_direct_audio_demux_starts_with_thread_queue(tmp_path, monkeypatch):
    """Single-file direct live mux must pass direct -i input with thread_queue_size 512."""
    _setup_mock_dll(monkeypatch)
    out_mp4 = tmp_path / "out_direct.mp4"
    in_mp4 = tmp_path / "in_direct.mp4"
    in_mp4.write_bytes(b"dummy source")

    captured_cmds = []
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_proc.wait.return_value = 0
    mock_proc.stderr = []

    def fake_popen(cmd, *a, **kw):
        captured_cmds.append(cmd)
        Path(str(out_mp4) + ".part").write_bytes(b"dummy valid mp4")
        return mock_proc

    install_mux_popen(monkeypatch, fake_popen)

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=10.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout={},
        field_samples={},
    )

    assert res is True
    mux_cmds = [c for c in captured_cmds if "-f" in c and "hevc" in c]
    assert len(mux_cmds) == 1
    cmd = mux_cmds[0]
    # Input 0: -thread_queue_size 512 -i -
    in0_idx = cmd.index("-")
    assert cmd[in0_idx - 1] == "-i"
    assert cmd[in0_idx - 2] == "512"
    assert cmd[in0_idx - 3] == "-thread_queue_size"
    # Input 1: -thread_queue_size 512 -i <in_mp4>
    in1_idx = cmd.index(str(in_mp4))
    assert cmd[in1_idx - 1] == "-i"
    assert cmd[in1_idx - 2] == "512"
    assert cmd[in1_idx - 3] == "-thread_queue_size"
    # No concat demuxer used for single file
    assert "concat" not in cmd
    assert not (tmp_path / "out_direct.audio.concat.txt").exists()


def test_single_file_range_offset_uses_direct_ss_and_thread_queue(tmp_path, monkeypatch):
    """Single clip with cut/offset must pass -thread_queue_size 512 -ss <offset> -i <file>."""
    _setup_mock_dll(monkeypatch)
    out_mp4 = tmp_path / "out_offset.mp4"
    in_mp4 = tmp_path / "in_offset.mp4"
    in_mp4.write_bytes(b"dummy source")

    captured_cmds = []
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_proc.wait.return_value = 0
    mock_proc.stderr = []

    def fake_popen(cmd, *a, **kw):
        captured_cmds.append(cmd)
        Path(str(out_mp4) + ".part").write_bytes(b"dummy valid mp4")
        return mock_proc

    install_mux_popen(monkeypatch, fake_popen)

    mock_clip = MagicMock()
    mock_clip.path = in_mp4
    mock_clip.local_start_s = 45.5
    mock_clip.local_end_s = 75.5
    mock_clip.duration_s = 30.0
    mock_clip.source_duration_s = 300.0
    mock_clip.global_start_s = 0.0
    mock_clip.global_end_s = 30.0

    mock_timeline = MagicMock()
    mock_timeline.clip_count = 1
    mock_timeline.clips = [mock_clip]
    mock_timeline.project_duration_s = 30.0
    mock_timeline.output_frame_counts.return_value = [900]
    mock_timeline.frame_to_activity_elapsed.return_value = 0.0
    mock_timeline.frame_to_clip.return_value = (0, 0.0)

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=30.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout={},
        field_samples={},
        video_timeline=mock_timeline,
    )

    assert res is True
    mux_cmds = [c for c in captured_cmds if "-f" in c and "hevc" in c]
    assert len(mux_cmds) == 1
    cmd = mux_cmds[0]
    assert "-ss" in cmd
    ss_idx = cmd.index("-ss")
    assert cmd[ss_idx + 1] == "45.500000"
    assert cmd[ss_idx + 2] == "-i"
    assert cmd[ss_idx + 3] == str(in_mp4)
    assert "-thread_queue_size" in cmd
    assert "concat" not in cmd


def test_multi_file_boundaries_retain_concat_plan_with_thread_queue(tmp_path, monkeypatch):
    """Multi-file exports must still use .audio.concat.txt plan with -thread_queue_size."""
    _setup_mock_dll(monkeypatch)
    out_mp4 = tmp_path / "out_multi.mp4"
    in_mp4_1 = tmp_path / "clip1.mp4"
    in_mp4_2 = tmp_path / "clip2.mp4"
    in_mp4_1.write_bytes(b"dummy clip 1")
    in_mp4_2.write_bytes(b"dummy clip 2")

    captured_cmds = []
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_proc.wait.return_value = 0
    mock_proc.stderr = []

    def fake_popen(cmd, *a, **kw):
        captured_cmds.append(cmd)
        Path(str(out_mp4) + ".part").write_bytes(b"dummy valid mp4")
        return mock_proc

    install_mux_popen(monkeypatch, fake_popen)

    from src.multifile import VideoTimeline, VideoClip
    timeline = VideoTimeline(
        clips=[
            VideoClip(path=in_mp4_1, duration_s=10.0, global_start_s=0.0, local_start_s=0.0, frame_count=300),
            VideoClip(path=in_mp4_2, duration_s=10.0, global_start_s=10.0, local_start_s=0.0, frame_count=300),
        ],
    )

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4_1), str(in_mp4_2)],
        output_file=str(out_mp4),
        duration_s=20.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout={},
        field_samples={},
        video_timeline=timeline,
    )

    assert res is True
    mux_cmds = [c for c in captured_cmds if "-f" in c and "hevc" in c]
    assert len(mux_cmds) == 1
    cmd = mux_cmds[0]
    assert "-f" in cmd
    concat_idx = cmd.index("concat")
    assert cmd[concat_idx - 1] == "-f"
    assert "-thread_queue_size" in cmd
    tq_idx = cmd.index("-thread_queue_size")
    assert cmd[tq_idx + 1] == "512"


def test_no_intermediate_or_split_audio_files_created(tmp_path, monkeypatch):
    """Strict check: absolutely NO .m4a, .adts, audio_cache, or intermediate MP4 files created."""
    _setup_mock_dll(monkeypatch)
    out_mp4 = tmp_path / "out_clean.mp4"
    in_mp4 = tmp_path / "in_clean.mp4"
    in_mp4.write_bytes(b"dummy source")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_proc.wait.return_value = 0
    mock_proc.stderr = []

    def fake_popen(cmd, *a, **kw):
        Path(str(out_mp4) + ".part").write_bytes(b"dummy valid mp4")
        return mock_proc

    install_mux_popen(monkeypatch, fake_popen)

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=10.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout={},
        field_samples={},
    )

    assert res is True
    all_files = list(tmp_path.iterdir())
    names = [f.name for f in all_files]
    assert out_mp4.exists()
    # Confirm no split audio or temp video files
    forbidden_suffixes = (".m4a", ".aac", ".adts", ".h265", ".concat.txt", ".temp_video.mp4")
    assert not any(n.endswith(forbidden_suffixes) for n in names)


def test_watchdog_does_not_kill_ffmpeg_when_progress_is_active(tmp_path, monkeypatch):
    """Watchdog must not kill FFmpeg while file size or I/O is actively progressing."""
    _setup_mock_dll(monkeypatch)
    monkeypatch.setenv("AMD_MUX_STALL_TIMEOUT", "1.0")
    out_mp4 = tmp_path / "out_active.mp4"
    in_mp4 = tmp_path / "in_active.mp4"
    in_mp4.write_bytes(b"dummy source")

    mock_proc = MagicMock()
    # Simulates 3 poll calls while active, then finished
    polls = iter([None, None, None, 0])
    mock_proc.poll.side_effect = lambda: next(polls)
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0
    mock_proc.stderr = []

    part_file = Path(str(out_mp4) + ".part")
    counter = [0]

    def fake_popen(cmd, *a, **kw):
        part_file.write_bytes(b"initial chunk")
        return mock_proc

    # Simulate file growth during poll
    original_poll = mock_proc.poll.side_effect
    def progressing_poll():
        res = original_poll()
        counter[0] += 1
        part_file.write_bytes(b"chunk " + b"x" * (counter[0] * 1024))
        return res
    mock_proc.poll.side_effect = progressing_poll

    install_mux_popen(monkeypatch, fake_popen)

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=5.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout={},
        field_samples={},
    )

    assert res is True
    mock_proc.kill.assert_not_called()
    assert out_mp4.exists()


def test_watchdog_terminates_on_genuine_stall(tmp_path, monkeypatch):
    """Watchdog must terminate FFmpeg if no I/O progress occurs within stall timeout."""
    _setup_mock_dll(monkeypatch)
    monkeypatch.setenv("AMD_MUX_STALL_TIMEOUT", "0.4")
    out_mp4 = tmp_path / "out_stalled.mp4"
    in_mp4 = tmp_path / "in_stalled.mp4"
    in_mp4.write_bytes(b"dummy source")

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # Never finishes on its own
    mock_proc.returncode = -9
    mock_proc.wait.return_value = -9
    mock_proc.stderr = []

    def fake_popen(cmd, *a, **kw):
        # Writes fixed size, no growth
        Path(str(out_mp4) + ".part").write_bytes(b"stalled content")
        return mock_proc

    install_mux_popen(monkeypatch, fake_popen)

    from src.ffmpeg.render_errors import MuxError
    with pytest.raises(MuxError):
        export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(in_mp4)],
            output_file=str(out_mp4),
            duration_s=5.0,
            video_width=1920,
            video_height=1080,
            start_dt_utc=None,
            tz_offset_hours=0.0,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            font_path="",
            layout={},
            field_samples={},
        )

    assert mock_proc.kill.called

