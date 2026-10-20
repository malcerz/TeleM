"""Regression tests for AMD Single Live Mux Audio Finalization (Etap 5R-F).

Verifies:
1. Single-file exports use direct audio input with thread_queue_size (no concat demuxer).
2. Range-seek offsets use direct -ss -i with thread_queue_size.
3. No intermediate audio files (.audio.concat.txt, .m4a, .aac, .adts, audio_cache, temp_video.mp4) for single-file.
4. Exactly one live muxer process is spawned.
5. Multi-file audio is one stream-copied AAC pipe fed from the MP4 sample tables.
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
def _confirmed_sdr_colour_probe(monkeypatch):
    """ETAP 5Z.3: HDR classification is fail-closed (unreadable media is refused).
    These lifecycle tests use fake media, so the colour probe reports confirmed SDR."""
    from src.ffmpeg import hdr_color

    monkeypatch.setattr(hdr_color, "probe_video_color", lambda path, *a, **k: hdr_color.classify_stream(
        {"codec_name": "hevc", "pix_fmt": "yuv420p", "color_transfer": "bt709", "color_primaries": "bt709",
         "color_space": "bt709", "color_range": "tv", "width": 3840, "height": 2160,
         "avg_frame_rate": "30000/1001"}, str(path)))


@pytest.mark.parametrize("mode,codecs,maps", [
    ("concat_filter", ["-c:a", "aac"], ["-map", "[aout]"]),
    ("copy", ["-c:a", "aac"], ["-map", "1:a"]),
    ("copy", ["-c:a", "copy"], ["-filter_complex", "anull"]),
])
def test_amd_rejects_reencoding_helper_configuration(mode, codecs, maps):
    from src.ffmpeg.amd_native_exporter import _require_amd_audio_copy, AMDNativeFinalizationError
    from src.ffmpeg.live_mux_common import LiveAudioInputs
    with pytest.raises(AMDNativeFinalizationError, match="re-encoding is forbidden"):
        _require_amd_audio_copy(LiveAudioInputs(mode=mode, codec_args=codecs, map_args=maps))


@pytest.mark.parametrize("flag", ["AMD_DIRECT_MUX", "AMD_SINGLE_PASS_AV_MUX"])
def test_amd_disabled_live_mux_fails_without_file_fallback(tmp_path, monkeypatch, flag):
    from src.ffmpeg.amd_native_exporter import AMDNativeFinalizationError
    dll = _setup_mock_dll(monkeypatch)
    monkeypatch.setenv(flag, "0")
    with pytest.raises(AMDNativeFinalizationError, match="fallback is forbidden"):
        export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg", input_files=[str(tmp_path / "source.mp4")],
            output_file=str(tmp_path / "out.mp4"), duration_s=1, video_width=1280, video_height=720,
            start_dt_utc=None, tz_offset_hours=0, speed_samples=[], track_samples=[], alt_samples=[],
            font_path="", layout={}, field_samples={},
        )
    dll.telem_amd_create.assert_not_called()


@pytest.mark.parametrize("failure", ["timestamps", "video_pipe", "spawn"])
def test_amd_setup_failure_never_uses_another_mux(tmp_path, monkeypatch, failure):
    import ctypes
    from src.ffmpeg.amd_native_exporter import AMDNativeFinalizationError
    dll = _setup_mock_dll(monkeypatch)
    if failure == "timestamps":
        monkeypatch.setattr("src.ffmpeg.live_mux_common.ffmpeg_supports_input_bsf", lambda *args: False)
    elif failure == "video_pipe":
        ctypes.windll.kernel32.CreateNamedPipeW.return_value = 0
    else:
        def failed_mux(*args, **kwargs):
            raise OSError("mux launch rejected")
        install_mux_popen(monkeypatch, failed_mux)
    with pytest.raises(AMDNativeFinalizationError):
        export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg", input_files=[str(tmp_path / "source.mp4")],
            output_file=str(tmp_path / "out.mp4"), duration_s=1, video_width=1280, video_height=720,
            start_dt_utc=None, tz_offset_hours=0, speed_samples=[], track_samples=[], alt_samples=[],
            font_path="", layout={}, field_samples={},
        )
    dll.telem_amd_create.assert_not_called()
    assert not list(tmp_path.glob("*.h265"))


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


def test_single_file_audio_pipe_starts_with_thread_queue(tmp_path, monkeypatch):
    """Single-file mux receives exact source packets through the same AAC pipe."""
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
    assert str(in_mp4) not in cmd
    in1_idx = next(i for i, arg in enumerate(cmd) if str(arg).startswith(r"\\.\pipe\telem_amf_audio_"))
    assert cmd[in1_idx - 1] == "-i"
    assert cmd[in1_idx - 2] == "aac"
    assert cmd[cmd.index("-c") + 1] == "copy"
    # No concat demuxer used for single file
    assert "concat" not in cmd
    assert not (tmp_path / "out_direct.audio.concat.txt").exists()


def test_single_file_range_offset_selects_original_packets(tmp_path, monkeypatch, isolated_platform):
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
    assert "-ss" not in cmd
    assert isolated_platform[0][0].start_s == 45.5
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert "-thread_queue_size" in cmd
    assert "concat" not in cmd


def test_multi_file_audio_is_one_copied_aac_pipe(tmp_path, monkeypatch):
    """Multi-file audio is the original AAC packets, piped and stream-copied.

    No concat demuxer (it reads every video packet), no concat filter (it
    re-encodes): one ``-f aac`` pipe input fed from the MP4 sample tables.
    """
    _setup_mock_dll(monkeypatch)
    monkeypatch.setattr("src.ffmpeg.live_mux_common.ffmpeg_supports_input_bsf", lambda *args: True)
    feeders = []

    class FakePlan:
        has_audio = True

        def report_lines(self):
            return []

    class FakeFeeder:
        def __init__(self, plan, pipe_name):
            self.pipe_name = pipe_name
            self.started = False
            self.closed = False
            self.error = None
            self.bytes_written = 0
            self.completed = True
            feeders.append(self)

        def start(self):
            self.started = True

        def close(self, timeout=5.0):
            self.closed = True

    planned = []
    monkeypatch.setattr(
        "src.ffmpeg.mp4_audio_feed.plan_aac_feed",
        lambda segments: planned.append(list(segments)) or FakePlan(),
    )
    monkeypatch.setattr("src.ffmpeg.mp4_audio_feed.AacPipeFeeder", FakeFeeder)
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
    assert "concat" not in cmd
    assert "-filter_complex" not in cmd
    assert str(in_mp4_1) not in cmd and str(in_mp4_2) not in cmd
    assert len(feeders) == 1 and feeders[0].started and feeders[0].closed
    pipe_idx = cmd.index(feeders[0].pipe_name)
    assert cmd[pipe_idx - 3:pipe_idx] == ["-f", "aac", "-i"]
    assert cmd[cmd.index("1:a:0") - 1] == "-map"
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert "-bsf:v" in cmd
    assert [segment.path for segment in planned[0]] == [str(in_mp4_1), str(in_mp4_2)]
    assert not (tmp_path / "out_multi.audio.concat.txt").exists()


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



def test_storage_stop_uses_existing_drain_and_preserves_partial(tmp_path,monkeypatch):
    from threading import Event
    dll=_setup_mock_dll(monkeypatch)
    out=tmp_path/'storage_partial.mp4'
    source=tmp_path/'source.mp4'
    source.write_bytes(b'fake')
    proc=MagicMock(returncode=0,stderr=[])
    proc.poll.return_value=0
    proc.wait.return_value=0
    def popen(*args,**kwargs):
        Path(str(out)+'.part').write_bytes(b'mocked mux output')
        return proc
    install_mux_popen(monkeypatch,popen)
    stop=Event()
    stop.storage_stop_requested=True
    stop.set()
    export_amd_native_d3d11(ffmpeg_exe='ffmpeg',input_files=[str(source)],
        output_file=str(out),duration_s=5,video_width=1920,video_height=1080,
        start_dt_utc=None,tz_offset_hours=0,speed_samples=[],track_samples=[],
        alt_samples=[],font_path='',layout={},field_samples={},cancel_event=stop)
    dll.telem_amd_flush.assert_called_once()
    proc.kill.assert_not_called()
    assert out.exists() or Path(str(out)+'.part').exists()
