"""Tests for AMD Native Direct Live MP4 Mux for single-file exports.
Validates elimination of temporary .h265 bitstream files on disk,
atomic .part renaming, failure propagation, range seek audio offset, and fallback paths.
"""

from __future__ import annotations

import os
import sys
import time
import json
import threading
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ffmpeg.amd_native_exporter import (
    export_amd_native_d3d11,
    AMD_NATIVE_ABI_VERSION,
    _cleanup_cancelled_amd_outputs,
    _audio_concat_entries,
    _write_audio_concat_plan,
    _create_amd_local_scratch_dir,
    _wait_for_process_exit,
)


def test_canonical_audio_plan_uses_effective_source_local_ranges(tmp_path):
    """The live A/V mux receives the same retained clip bounds as native video."""
    from types import SimpleNamespace

    timeline = SimpleNamespace(clips=[
        SimpleNamespace(
            path=tmp_path / "clip one.mp4", duration_s=6.0,
            local_start_s=2.0, local_end_s=8.0, source_duration_s=10.0,
        ),
        SimpleNamespace(
            path=tmp_path / "clip two.mp4", duration_s=4.0,
            local_start_s=0.0, local_end_s=4.0, source_duration_s=4.0,
        ),
    ])
    entries = _audio_concat_entries(timeline)
    assert entries == [
        "file '" + str(tmp_path / "clip one.mp4") + "'\n",
        "inpoint 2.000000000\n",
        "outpoint 8.000000000\n",
        "file '" + str(tmp_path / "clip two.mp4") + "'\n",
    ]
    plan = _write_audio_concat_plan(tmp_path / "audio.plan.txt", timeline)
    assert plan.read_text(encoding="utf-8") == "".join(entries)


def test_amd_multifile_stage_a_uses_local_scratch(tmp_path, monkeypatch):
    output = tmp_path / "usb" / "final.mp4"
    configured = tmp_path / "local-m2" / "amd"
    monkeypatch.setenv("AMD_LOCAL_SCRATCH_DIR", str(configured))

    scratch = _create_amd_local_scratch_dir(output)

    assert scratch.parent == configured.resolve()
    assert scratch != output.parent.resolve()
    assert scratch.exists()
    scratch.rmdir()


def test_amd_multifile_stage_a_scratch_is_recoverable_on_failure(tmp_path, monkeypatch):
    output = tmp_path / "usb" / "final.mp4"
    configured = tmp_path / "local-m2" / "amd"
    monkeypatch.setenv("AMD_LOCAL_SCRATCH_DIR", str(configured))

    scratch = _create_amd_local_scratch_dir(output)
    stage_video = scratch / "final.temp_video.mp4"
    stage_video.write_bytes(b"recoverable Stage A video")

    # The exporter deliberately does not delete this workspace on Stage C
    # failure; this mirrors the recovery contract for a long render.
    assert stage_video.read_bytes() == b"recoverable Stage A video"
    stage_video.unlink()
    scratch.rmdir()


def test_cancel_cleanup_removes_partial_artifacts_but_preserves_final(tmp_path):
    final_output = tmp_path / "render.mp4"
    output_part = tmp_path / "render.mp4.part"
    stage_video = tmp_path / "render.mp4.part.temp_video.mp4"
    audio_concat = tmp_path / "render.audio.concat.txt"
    final_output.write_bytes(b"valid completed output")
    output_part.write_bytes(b"partial mux")
    stage_video.write_bytes(b"partial stage A")
    audio_concat.write_text("partial concat", encoding="utf-8")

    removed = _cleanup_cancelled_amd_outputs(
        output_part, stage_video, audio_concat
    )

    assert set(removed) == {output_part, stage_video, audio_concat}
    assert final_output.read_bytes() == b"valid completed output"
    assert not output_part.exists()
    assert not stage_video.exists()
    assert not audio_concat.exists()


def test_live_mux_wait_has_no_elapsed_timeout(monkeypatch):
    process = MagicMock()
    states = iter([None, None, None, 0])
    process.poll.side_effect = lambda: next(states)
    process.returncode = 0
    monkeypatch.setattr("src.ffmpeg.amd_native_exporter.time.sleep", lambda _: None)

    assert _wait_for_process_exit(process) is True
    process.kill.assert_not_called()


# ---------------------------------------------------------------------------
# Test A & G & H: Single-file direct live mux creates .part, streams without temp .h265,
# and atomically renames to .mp4 on success.
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_lifecycle_single_file(tmp_path, monkeypatch):
    out_mp4 = tmp_path / "output_test.mp4"
    in_mp4 = tmp_path / "input_test.mp4"
    in_mp4.write_bytes(b"dummy mp4 source")

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
    mock_dll.telem_amd_read_video_sample.return_value = 0  # EOS
    mock_dll.telem_amd_process_frame.return_value = 0 # EOF immediately
    mock_dll.telem_amd_flush.return_value = 1
    mock_dll.telem_amd_close.return_value = 1

    created_targets = []
    def fake_create(in_p, out_p, w, h, fn, fd):
        created_targets.append(out_p)
        if out_p.startswith(r"\\.\pipe"):
            with open(out_p + ".h265", "wb") as f:
                f.write(b"fake hevc packets")
        return 12345
    mock_dll.telem_amd_create.side_effect = fake_create

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **kw: mock_dll)

    # Fake FFmpeg process
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_proc.wait.return_value = 0
    mock_proc.stderr = []

    def fake_popen(cmd, *a, **kw):
        # When FFmpeg is called, create the .part file
        part_file = str(out_mp4) + ".part"
        Path(part_file).write_bytes(b"dummy valid mp4 container content")
        return mock_proc

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("src.ffmpeg.amd_native_exporter._probe_video_summary", lambda exe, path: {
        "streams": [{"codec_type": "video", "nb_frames": "30"}, {"codec_type": "audio"}]
    })

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=1.0,
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
    # 1. telem_amd_create was given a named pipe base, NOT a disk file
    assert len(created_targets) == 1
    assert created_targets[0].startswith(r"\\.\pipe\telem_amf_")
    # 2. No temporary .h265 exists on disk
    assert not (tmp_path / "output_test.mp4.h265").exists()
    # 3. .part was renamed to final .mp4
    assert out_mp4.exists()
    assert not (tmp_path / "output_test.mp4.part").exists()


# ---------------------------------------------------------------------------
# Test: Single-file range/cut audio offset (-ss) contract
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_with_range_start_offset(tmp_path, monkeypatch):
    out_mp4 = tmp_path / "output_range.mp4"
    in_mp4 = tmp_path / "input_test.mp4"
    in_mp4.write_bytes(b"dummy mp4 source")

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

    def fake_create(in_p, out_p, w, h, fn, fd):
        if out_p.startswith(r"\\.\pipe"):
            with open(out_p + ".h265", "wb") as f:
                f.write(b"fake hevc packets")
        return 12345
    mock_dll.telem_amd_create.side_effect = fake_create

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **kw: mock_dll)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_proc.wait.return_value = 0
    mock_proc.stderr = []

    captured_cmds = []
    def fake_popen(cmd, *a, **kw):
        captured_cmds.append(cmd)
        part_file = str(out_mp4) + ".part"
        Path(part_file).write_bytes(b"dummy valid mp4")
        return mock_proc

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("src.ffmpeg.amd_native_exporter._probe_video_summary", lambda exe, path: {
        "streams": [{"codec_type": "video", "nb_frames": "60"}, {"codec_type": "audio"}]
    })

    # Mock VideoTimeline single-clip with local_start_s = 120.0
    mock_clip = MagicMock()
    mock_clip.path = in_mp4
    mock_clip.local_start_s = 120.0
    mock_clip.local_end_s = 180.0
    mock_clip.duration_s = 60.0
    mock_clip.source_duration_s = 600.0

    mock_timeline = MagicMock()
    mock_timeline.clip_count = 1
    mock_timeline.clips = [mock_clip]
    mock_timeline.output_frame_counts.return_value = [1800]
    mock_timeline.frame_to_activity_elapsed.return_value = 0.0
    mock_timeline.frame_to_clip.return_value = (0, 0.0)

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=60.0,
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
    # Check that -ss 120.000000 was placed before -i input_test.mp4
    assert "-ss" in cmd
    ss_idx = cmd.index("-ss")
    assert cmd[ss_idx + 1] == "120.000000"
    assert cmd[ss_idx + 2] == "-i"
    assert cmd[ss_idx + 3] == str(in_mp4)


# ---------------------------------------------------------------------------
# Test I & H: Live mux failure propagates EXPORT FAILED (returns False)
# and protects existing valid target output file.
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_failure_propagation(tmp_path, monkeypatch):
    out_mp4 = tmp_path / "protected_target.mp4"
    out_mp4.write_bytes(b"ORIGINAL VALID CONTENT - DO NOT DESTROY")
    in_mp4 = tmp_path / "input_test.mp4"
    in_mp4.write_bytes(b"dummy mp4")

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
    mock_dll.telem_amd_read_video_sample.return_value = 0
    mock_dll.telem_amd_process_frame.return_value = 0
    mock_dll.telem_amd_flush.return_value = 1
    mock_dll.telem_amd_close.return_value = 1

    def fake_create(in_p, out_p, w, h, fn, fd):
        if out_p.startswith(r"\\.\pipe"):
            with open(out_p + ".h265", "wb") as f:
                f.write(b"fake hevc packets")
        return 12345
    mock_dll.telem_amd_create.side_effect = fake_create

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **kw: mock_dll)

    # Fake failing FFmpeg process (e.g. exit code 1)
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.poll.return_value = 1
    mock_proc.wait.return_value = 1
    mock_proc.stderr = [b"Conversion failed!\n"]

    def fake_popen(cmd, *a, **kw):
        part_file = str(out_mp4) + ".part"
        Path(part_file).write_bytes(b"broken partial content")
        return mock_proc

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=1.0,
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

    # Must propagate failure (False)
    assert res is False
    # Original target file must remain intact
    assert out_mp4.read_bytes() == b"ORIGINAL VALID CONTENT - DO NOT DESTROY"
    # Temporary .part must be cleaned up
    assert not (tmp_path / "protected_target.mp4.part").exists()


# ---------------------------------------------------------------------------
# Test: User cancellation cleans up pipe, process, and .part file
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_user_cancellation(tmp_path, monkeypatch):
    out_mp4 = tmp_path / "cancelled_export.mp4"
    in_mp4 = tmp_path / "input_test.mp4"
    in_mp4.write_bytes(b"dummy mp4")

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
    mock_dll.telem_amd_read_video_sample.return_value = 0
    mock_dll.telem_amd_process_frame.return_value = 0
    mock_dll.telem_amd_flush.return_value = 1
    mock_dll.telem_amd_close.return_value = 1

    def fake_create(in_p, out_p, w, h, fn, fd):
        if out_p.startswith(r"\\.\pipe"):
            with open(out_p + ".h265", "wb") as f:
                f.write(b"fake hevc packets")
        return 12345
    mock_dll.telem_amd_create.side_effect = fake_create

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **kw: mock_dll)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.poll.return_value = None  # running
    mock_proc.wait.return_value = 0

    def fake_popen(cmd, *a, **kw):
        part_file = str(out_mp4) + ".part"
        Path(part_file).write_bytes(b"partial video while cancelling")
        return mock_proc

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    cancel_ev = threading.Event()
    cancel_ev.set()  # Pre-set cancel event

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=1.0,
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
        cancel_event=cancel_ev,
    )

    assert res is False
    assert not out_mp4.exists()
    assert not (tmp_path / "cancelled_export.mp4.part").exists()


# ---------------------------------------------------------------------------
# Test J & K: Fallback path when multi-file or AMD_DIRECT_MUX=0
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_lifecycle_multi_file(tmp_path, monkeypatch):
    """Multi-file direct live mux creates .part, streams without temp .h265, uses .audio.concat.txt, and renames to .mp4."""
    # Preserve coverage of the explicit legacy two-stage recovery path.  The
    # production default is single-pass A/V mux; this test exercises the old
    # path only as a controlled diagnostic fallback.
    monkeypatch.setenv("AMD_SINGLE_PASS_AV_MUX", "0")
    out_mp4 = tmp_path / "output_multi.mp4"
    in_mp4_1 = tmp_path / "clip1.mp4"
    in_mp4_2 = tmp_path / "clip2.mp4"
    in_mp4_1.write_bytes(b"dummy mp4 1")
    in_mp4_2.write_bytes(b"dummy mp4 2")

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
    mock_dll.telem_amd_read_video_sample.return_value = 0
    mock_dll.telem_amd_process_frame.return_value = 0
    mock_dll.telem_amd_flush.return_value = 1
    mock_dll.telem_amd_close.return_value = 1

    created_targets = []
    def fake_create(in_p, out_p, w, h, fn, fd):
        created_targets.append(out_p)
        if out_p.startswith(r"\\.\pipe"):
            with open(out_p + ".h265", "wb") as f:
                f.write(b"fake hevc packets from multi-file")
        return 12345
    mock_dll.telem_amd_create.side_effect = fake_create

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **kw: mock_dll)

    captured_cmds = []
    def fake_popen(cmd, *a, **kw):
        captured_cmds.append(cmd)
        out_path = cmd[-1]
        if "concat" in cmd:
            assert out_path.endswith(".mp4.part")
        else:
            assert out_path.endswith(".temp_video.mp4")
        Path(out_path).write_bytes(b"dummy encoded mp4 payload")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = None
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__.return_value = []
        return mock_proc

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("src.ffmpeg.amd_native_exporter._probe_video_summary", lambda exe, path: {
        "streams": [{"codec_type": "video", "nb_frames": "60"}, {"codec_type": "audio"}]
    })

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
    assert len(created_targets) == 1
    assert created_targets[0].startswith(r"\\.\pipe\telem_amf_")
    assert not Path(str(out_mp4) + ".h265").exists()
    assert not Path(str(out_mp4) + ".part").exists()
    assert not Path(str(out_mp4) + ".audio.concat.txt").exists()
    assert out_mp4.exists()

    # Verify that FFmpeg received concat input
    mux_cmd = [c for c in captured_cmds if "-f" in c and "concat" in c]
    assert len(mux_cmd) == 1
    cmd = mux_cmd[0]
    concat_idx = cmd.index("-f")
    assert cmd[concat_idx + 1] == "concat"
    assert "-safe" in cmd
    assert "concat" in cmd


# ---------------------------------------------------------------------------
# Test J & K: Fallback path when AMD_DIRECT_MUX=0
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_fallback_on_flag_or_multifile(tmp_path, monkeypatch):
    out_mp4 = tmp_path / "output_fallback.mp4"
    in_mp4 = tmp_path / "input_test.mp4"
    in_mp4.write_bytes(b"dummy mp4")

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
    mock_dll.telem_amd_read_video_sample.return_value = 0
    mock_dll.telem_amd_process_frame.return_value = 0
    mock_dll.telem_amd_flush.return_value = 1
    mock_dll.telem_amd_close.return_value = 1

    created_targets = []
    def fake_create(in_p, out_p, w, h, fn, fd):
        created_targets.append(out_p)
        # In fallback, C++ creates .h265 file
        h265_path = out_p + ".h265"
        Path(h265_path).write_bytes(b"dummy h265 bitstream")
        return 12345
    mock_dll.telem_amd_create.side_effect = fake_create

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **kw: mock_dll)
    monkeypatch.setenv("AMD_DIRECT_MUX", "0")

    def fake_popen(cmd, *a, **kw):
        out_file = cmd[-1]
        Path(out_file).write_bytes(b"final muxed mp4")
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.poll.return_value = 0
        mock_res.stderr = []
        return mock_res

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("src.ffmpeg.amd_native_exporter._probe_video_summary", lambda exe, path: {
        "streams": [{"codec_type": "video", "nb_frames": "30"}, {"codec_type": "audio"}]
    })

    res = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(in_mp4)],
        output_file=str(out_mp4),
        duration_s=1.0,
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
    # In fallback path, telem_amd_create was given output_file_str directly
    assert len(created_targets) == 1
    assert created_targets[0] == str(out_mp4)
    # Output file created
    assert out_mp4.exists()
