"""Single-pass live A/V mux helpers shared by the AMD, NVIDIA and Intel paths."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from src.ffmpeg.live_av_mux import (
    AudioSegment,
    LiveMuxConfigError,
    audio_segments_from_timeline,
    build_live_audio_inputs,
    ffmpeg_supports_input_bsf,
    raw_video_timestamp_args,
)
from src.multifile import VideoClip, VideoTimeline


def test_single_segment_is_stream_copied_without_probe():
    def fail_probe(_path):
        raise AssertionError("single segment must not be probed")

    live = build_live_audio_inputs(
        [AudioSegment("a.mp4", start_s=45.5, duration_s=30.0)],
        first_input_index=1,
        has_audio=fail_probe,
        thread_queue_size=512,
    )
    assert live.mode == "copy"
    assert live.input_args == [
        "-thread_queue_size", "512", "-t", "30.000000", "-ss", "45.500000", "-i", "a.mp4",
    ]
    assert live.map_args == ["-map", "1:a:0?"]
    assert live.codec_args == ["-c:a", "copy"]


def test_multi_segment_uses_separate_inputs_and_concat_filter():
    live = build_live_audio_inputs(
        [AudioSegment("a.mp4", start_s=2.0), AudioSegment("b.mp4", duration_s=16.0)],
        first_input_index=1,
        has_audio=lambda _path: True,
    )
    assert live.mode == "concat_filter"
    assert "concat" not in live.input_args
    assert live.input_args == ["-ss", "2.000000", "-i", "a.mp4", "-t", "16.000000", "-i", "b.mp4"]
    assert live.map_args == [
        "-filter_complex", "[1:a:0][2:a:0]concat=n=2:v=0:a=1[aout]", "-map", "[aout]",
    ]
    assert live.codec_args[:2] == ["-c:a", "aac"]
    assert live.input_count == 2


def test_clip_without_audio_gets_silence_of_its_length():
    live = build_live_audio_inputs(
        [AudioSegment("a.mp4", duration_s=10.0), AudioSegment("mute.mp4", duration_s=5.0)],
        first_input_index=1,
        has_audio=lambda path: path != "mute.mp4",
    )
    assert live.input_args[-6:] == [
        "-f", "lavfi", "-t", "5.000000", "-i", "anullsrc=r=48000:cl=stereo",
    ]


def test_no_audio_anywhere_means_video_only():
    live = build_live_audio_inputs(
        [AudioSegment("a.mp4"), AudioSegment("b.mp4")],
        first_input_index=1,
        has_audio=lambda _path: False,
    )
    assert not live.has_audio
    assert live.input_args == [] and live.input_count == 0


def test_timeline_segments_keep_source_local_bounds(tmp_path):
    timeline = VideoTimeline(clips=[
        VideoClip(path=tmp_path / "a.mp4", duration_s=8.0, local_start_s=2.0, source_duration_s=10.0),
        VideoClip(path=tmp_path / "b.mp4", duration_s=6.0, local_start_s=0.0, source_duration_s=20.0),
    ])
    assert audio_segments_from_timeline(timeline) == [
        AudioSegment(str(tmp_path / "a.mp4"), start_s=2.0, duration_s=None),
        AudioSegment(str(tmp_path / "b.mp4"), start_s=0.0, duration_s=6.0),
    ]


def test_strict_mode_reports_ffprobe_failure_instead_of_silence(tmp_path):
    broken = tmp_path / "not_a_video.mp4"
    broken.write_bytes(b"not an mp4")
    with pytest.raises(LiveMuxConfigError, match="ffprobe failed"):
        build_live_audio_inputs(
            [AudioSegment(str(broken)), AudioSegment(str(broken))],
            first_input_index=1,
            ffprobe_exe=shutil.which("ffprobe") or "ffprobe",
            strict=True,
        )


def test_missing_ffprobe_is_an_error_in_strict_mode():
    with pytest.raises(LiveMuxConfigError):
        build_live_audio_inputs(
            [AudioSegment("a.mp4"), AudioSegment("b.mp4")],
            first_input_index=1,
            ffprobe_exe="ffprobe-does-not-exist",
            strict=True,
        )


def test_required_timestamps_fail_loudly_without_input_bsf(monkeypatch):
    monkeypatch.setattr("src.ffmpeg.live_mux_common.ffmpeg_supports_input_bsf", lambda *args: False)
    with pytest.raises(LiveMuxConfigError, match="input -bsf"):
        raw_video_timestamp_args("ffmpeg", "hevc", 30000, 1001, required=True)
    assert raw_video_timestamp_args("ffmpeg", "hevc", 30000, 1001) == []


def test_container_formats_need_no_timestamp_filter():
    assert raw_video_timestamp_args("ffmpeg", "ivf", 30000, 1001) == []


def _ffmpeg_with_input_bsf() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe and ffmpeg_supports_input_bsf(exe):
        return exe
    return None


@pytest.mark.skipif(_ffmpeg_with_input_bsf() is None, reason="needs FFmpeg 7.1+ on PATH")
def test_live_mux_reads_audio_while_video_streams(tmp_path):
    """Audio must be demuxed while video streams in, not after stdin closes."""
    ffmpeg = _ffmpeg_with_input_bsf()
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    sources = []
    for index in range(2):
        source = tmp_path / f"src{index}.mp4"
        subprocess.run([
            ffmpeg, "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30000/1001",
            "-f", "lavfi", "-i", f"sine=f={440 * (index + 1)}:r=48000",
            "-t", "6", "-c:v", "mpeg4", "-q:v", "2", "-c:a", "aac", "-ac", "2", str(source),
        ], check=True)
        sources.append(source)
    encoded = tmp_path / "enc.hevc"
    result = subprocess.run([
        ffmpeg, "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30000/1001", "-t", "10",
        "-c:v", "libx265", "-x265-params", "bframes=0:log-level=error", "-f", "hevc", str(encoded),
    ])
    if result.returncode != 0:
        pytest.skip("libx265 not available")

    live = build_live_audio_inputs(
        [AudioSegment(str(sources[0]), start_s=1.0), AudioSegment(str(sources[1]), duration_s=5.0)],
        first_input_index=1,
        ffprobe_exe=ffprobe,
    )
    process = subprocess.Popen([
        ffmpeg, "-debug_ts", "-y",
        "-f", "hevc", "-r", "30000/1001",
        *raw_video_timestamp_args(ffmpeg, "hevc", 30000, 1001),
        "-i", "-",
        *live.input_args,
        "-map", "0:v", *live.map_args,
        "-t", "10", "-c:v", "copy", *live.codec_args, "-f", "mp4", str(tmp_path / "out.mp4"),
    ], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    audio_demuxed = []
    stdin_closed = threading.Event()

    def read_stderr():
        for line in process.stderr:
            if b"demuxer -> " in line and b"type:audio" in line:
                audio_demuxed.append(stdin_closed.is_set())

    reader = threading.Thread(target=read_stderr)
    reader.start()
    # Feed video like a real-time encoder would, not all at once.
    data = encoded.read_bytes()
    step = max(1, len(data) // 40)
    for offset in range(0, len(data), step):
        process.stdin.write(data[offset:offset + step])
        process.stdin.flush()
        time.sleep(0.05)
    stdin_closed.set()
    process.stdin.close()
    assert process.wait(timeout=60) == 0
    reader.join(timeout=10)

    assert audio_demuxed, "output has no audio"
    read_during_video = audio_demuxed.count(False) / len(audio_demuxed)
    assert read_during_video > 0.5
