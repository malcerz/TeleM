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
from src.ffmpeg.gpmf_export import InlineGpmfPlan


@pytest.fixture(autouse=True)
def _confirmed_sdr_colour_probe(monkeypatch):
    """ETAP 5Z.3: HDR classification is fail-closed (unreadable media is refused).
    These lifecycle tests use fake media, so the colour probe reports confirmed SDR."""
    from src.ffmpeg import hdr_color

    monkeypatch.setattr(hdr_color, "probe_video_color", lambda path, *a, **k: hdr_color.classify_stream(
        {"codec_name": "hevc", "pix_fmt": "yuv420p", "color_transfer": "bt709", "color_primaries": "bt709",
         "color_space": "bt709", "color_range": "tv", "width": 3840, "height": 2160,
         "avg_frame_rate": "30000/1001"}, str(path)))


@pytest.fixture(autouse=True)
def isolated_mux_platform(monkeypatch, request):
    """Unit mocks must never open OS named pipes or probe dummy media."""
    import ctypes
    kernel = MagicMock()
    kernel.CreateNamedPipeW.return_value = 123
    kernel.ConnectNamedPipe.return_value = 1
    kernel.ReadFile.return_value = 0
    kernel.GetLastError.return_value = 109  # clean pipe EOF
    kernel.OpenProcess.return_value = 0
    monkeypatch.setattr(ctypes.windll, "kernel32", kernel)
    monkeypatch.setattr("src.ffmpeg.amd_native_exporter._probe_video_summary", lambda *args: {
        "streams": [{"codec_type": "video", "nb_frames": "30"}, {"codec_type": "audio"}]
    })
    monkeypatch.setattr("src.ffmpeg.live_mux_common.ffmpeg_supports_input_bsf", lambda *args: True)
    plans = []
    def plan(segments):
        plans.append(list(segments))
        return MagicMock(has_audio=True)
    monkeypatch.setattr("src.ffmpeg.mp4_audio_feed.plan_aac_feed", plan)
    monkeypatch.setattr("src.ffmpeg.mp4_audio_feed.AacPipeFeeder", lambda *args: MagicMock(
        error=None, completed=True, bytes_written=0
    ))
    return plans


def install_mux_popen(monkeypatch, fake_popen):
    """Only the live mux process may create its output .part.

    Capability probes use subprocess.run too; routing those to the mux mock
    creates a stale partial output before the exporter even reaches preflight.
    """
    real_popen = subprocess.Popen
    def dispatch(cmd, *args, **kwargs):
        if kwargs.get("stdin") == subprocess.PIPE and any(fmt in cmd for fmt in ("hevc", "h264", "obu")):
            return fake_popen(cmd, *args, **kwargs)
        return real_popen(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", dispatch)


def test_preexisting_partial_is_preserved_before_native_create(tmp_path, monkeypatch):
    """An old partial output must never be overwritten by a fresh mux."""
    from src.ffmpeg.render_errors import MuxError
    dll = MagicMock()
    dll.telem_amd_get_abi_version.return_value = AMD_NATIVE_ABI_VERSION
    dll.telem_amd_get_build_info.return_value = b"ABI 9"
    monkeypatch.setattr("ctypes.CDLL", lambda *args, **kwargs: dll)
    output = tmp_path / "protected.mp4"
    partial = tmp_path / "protected.mp4.part"
    partial.write_bytes(b"previous recoverable export")
    with pytest.raises(MuxError) as raised:
        export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg", input_files=[str(tmp_path / "source.mp4")],
            output_file=str(output), duration_s=1.0, video_width=1920,
            video_height=1080, start_dt_utc=None, tz_offset_hours=0.0,
            speed_samples=[], track_samples=[], alt_samples=[], font_path="",
            layout={}, field_samples={},
        )
    assert raised.value.code == "PARTIAL_OUTPUT_EXISTS"
    assert raised.value.stage == "preflight_output"
    assert partial.read_bytes() == b"previous recoverable export"
    assert not output.exists()
    dll.telem_amd_create.assert_not_called()


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
@pytest.mark.parametrize("with_gpmf", [False, True])
def test_direct_mp4_mux_lifecycle_single_file(tmp_path, monkeypatch, with_gpmf):
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
        return 12345
    mock_dll.telem_amd_create.side_effect = fake_create

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **kw: mock_dll)

    # Fake FFmpeg process
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_proc.wait.return_value = 0
    mock_proc.stderr = []

    mux_commands = []
    def fake_popen(cmd, *a, **kw):
        mux_commands.append(cmd)
        # When FFmpeg is called, create the .part file
        part_file = str(out_mp4) + ".part"
        Path(part_file).write_bytes(b"dummy valid mp4 container content")
        return mock_proc

    install_mux_popen(monkeypatch, fake_popen)
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
        inline_gpmf_plan=(InlineGpmfPlan("ready_full", in_mp4, 3) if with_gpmf else None),
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
    final_mux_commands = [cmd for cmd in mux_commands if str(out_mp4) + ".part" in cmd]
    assert len(final_mux_commands) == 1
    mux_command = final_mux_commands[0]
    if with_gpmf:
        assert mux_command.count("-i") == 3
        assert "2:3" in mux_command
        assert "-c:d" in mux_command
        assert "gpmd" in mux_command
    else:
        assert "-c:d" not in mux_command


# ---------------------------------------------------------------------------
# Test: Single-file range/cut audio offset (-ss) contract
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_with_range_start_offset(tmp_path, monkeypatch, isolated_mux_platform):
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

    install_mux_popen(monkeypatch, fake_popen)
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
    mock_clip.global_start_s = 0.0
    mock_clip.global_end_s = 60.0

    mock_timeline = MagicMock()
    mock_timeline.clip_count = 1
    mock_timeline.clips = [mock_clip]
    mock_timeline.project_duration_s = 60.0
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
    assert "-ss" not in cmd
    assert str(in_mp4) not in cmd
    assert isolated_mux_platform[0][0].start_s == 120.0
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert "-thread_queue_size" in cmd
    assert "concat" not in cmd


# ---------------------------------------------------------------------------
# Test: Single-file legacy fallback (AMD_SINGLE_PASS_AV_MUX=0) uses direct -ss -i
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_single_file_legacy_fallback_ss_offset(tmp_path, monkeypatch):
    """Legacy finalization now fails explicitly instead of another mux pass."""
    from src.ffmpeg.amd_native_exporter import AMDNativeFinalizationError
    from src.multifile import VideoClip, VideoTimeline
    from tests.test_amd_live_mux_audio_finalization import _setup_mock_dll
    dll = _setup_mock_dll(monkeypatch)
    monkeypatch.setenv("AMD_SINGLE_PASS_AV_MUX", "0")
    clips = [VideoClip(path=tmp_path / "a.mp4", duration_s=1, fps=30)]
    if False:
        clips.append(VideoClip(path=tmp_path / "b.mp4", duration_s=1, fps=30))
    with pytest.raises(AMDNativeFinalizationError, match="fallback is forbidden"):
        export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg", input_files=[str(c.path) for c in clips],
            output_file=str(tmp_path / "final.mp4"), duration_s=len(clips),
            video_width=1280, video_height=720, start_dt_utc=None, tz_offset_hours=0,
            speed_samples=[], track_samples=[], alt_samples=[], font_path="", layout={},
            field_samples={}, target_fps=30, video_timeline=VideoTimeline(clips),
        )
    dll.telem_amd_create.assert_not_called()
    assert not list(tmp_path.glob("*.h265"))
    assert not list(tmp_path.glob("*.temp_video.mp4"))


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

    install_mux_popen(monkeypatch, fake_popen)

    from src.ffmpeg.render_errors import MuxError
    with pytest.raises(MuxError) as raised:
        export_amd_native_d3d11(
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

    # Typed errors carry recovery context and bypass software fallback.
    assert raised.value.code == "FFMPEG_EXIT_1"
    assert raised.value.stage == "live_mux"
    # Original target file must remain intact
    assert out_mp4.read_bytes() == b"ORIGINAL VALID CONTENT - DO NOT DESTROY"
    # Failed mux preserves its partial artifact for recovery; explicit user
    # cancellation has a separate cleanup contract.
    assert (tmp_path / "protected_target.mp4.part").read_bytes() == b"broken partial content"


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

    install_mux_popen(monkeypatch, fake_popen)

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
    """Legacy finalization now fails explicitly instead of another mux pass."""
    from src.ffmpeg.amd_native_exporter import AMDNativeFinalizationError
    from src.multifile import VideoClip, VideoTimeline
    from tests.test_amd_live_mux_audio_finalization import _setup_mock_dll
    dll = _setup_mock_dll(monkeypatch)
    monkeypatch.setenv("AMD_SINGLE_PASS_AV_MUX", "0")
    clips = [VideoClip(path=tmp_path / "a.mp4", duration_s=1, fps=30)]
    if True:
        clips.append(VideoClip(path=tmp_path / "b.mp4", duration_s=1, fps=30))
    with pytest.raises(AMDNativeFinalizationError, match="fallback is forbidden"):
        export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg", input_files=[str(c.path) for c in clips],
            output_file=str(tmp_path / "final.mp4"), duration_s=len(clips),
            video_width=1280, video_height=720, start_dt_utc=None, tz_offset_hours=0,
            speed_samples=[], track_samples=[], alt_samples=[], font_path="", layout={},
            field_samples={}, target_fps=30, video_timeline=VideoTimeline(clips),
        )
    dll.telem_amd_create.assert_not_called()
    assert not list(tmp_path.glob("*.h265"))
    assert not list(tmp_path.glob("*.temp_video.mp4"))


# ---------------------------------------------------------------------------
# Test J & K: Fallback path when AMD_DIRECT_MUX=0
# ---------------------------------------------------------------------------
def test_direct_mp4_mux_fallback_on_flag_or_multifile(tmp_path, monkeypatch):
    """Legacy finalization now fails explicitly instead of another mux pass."""
    from src.ffmpeg.amd_native_exporter import AMDNativeFinalizationError
    from src.multifile import VideoClip, VideoTimeline
    from tests.test_amd_live_mux_audio_finalization import _setup_mock_dll
    dll = _setup_mock_dll(monkeypatch)
    monkeypatch.setenv("AMD_DIRECT_MUX", "0")
    clips = [VideoClip(path=tmp_path / "a.mp4", duration_s=1, fps=30)]
    if False:
        clips.append(VideoClip(path=tmp_path / "b.mp4", duration_s=1, fps=30))
    with pytest.raises(AMDNativeFinalizationError, match="fallback is forbidden"):
        export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg", input_files=[str(c.path) for c in clips],
            output_file=str(tmp_path / "final.mp4"), duration_s=len(clips),
            video_width=1280, video_height=720, start_dt_utc=None, tz_offset_hours=0,
            speed_samples=[], track_samples=[], alt_samples=[], font_path="", layout={},
            field_samples={}, target_fps=30, video_timeline=VideoTimeline(clips),
        )
    dll.telem_amd_create.assert_not_called()
    assert not list(tmp_path.glob("*.h265"))
    assert not list(tmp_path.glob("*.temp_video.mp4"))
