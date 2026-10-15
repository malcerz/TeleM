"""Lossless AAC feed for the AMD multi-file live mux."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import uuid

import pytest

from src.ffmpeg.live_mux_common import AudioSegment, LiveMuxConfigError, ffmpeg_supports_input_bsf
from src.ffmpeg import mp4_audio_feed
from src.ffmpeg.mp4_audio_feed import AacPipeFeeder, AacTrack, iter_adts, open_aac_track, plan_aac_feed

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="needs ffmpeg and ffprobe on PATH")


def _make_clip(path, seconds=4, audio=True, rate=48000, freq=440):
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30000/1001"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f={freq}:r={rate}", "-c:a", "aac", "-ac", "2"]
    cmd += ["-t", str(seconds), "-c:v", "mpeg4", str(path)]
    subprocess.run(cmd, check=True)
    return str(path)


def _packet_hashes(path):
    out = subprocess.run([
        FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_packets", "-show_data_hash", "MD5",
        "-show_entries", "packet=data_hash", "-of", "json", str(path),
    ], capture_output=True, text=True, check=True).stdout
    return [packet["data_hash"] for packet in json.loads(out)["packets"]]


@needs_ffmpeg
def test_adts_frames_carry_the_original_packets(tmp_path):
    clip = _make_clip(tmp_path / "a.mp4")
    track = open_aac_track(clip)
    stream = b"".join(iter_adts(track, range(len(track.sizes))))
    payloads, offset = [], 0
    while offset < len(stream):
        frame_len = ((stream[offset + 3] & 3) << 11) | (stream[offset + 4] << 3) | (stream[offset + 5] >> 5)
        payloads.append("MD5:" + hashlib.md5(stream[offset + 7:offset + frame_len]).hexdigest())
        offset += frame_len
    assert payloads == _packet_hashes(clip)


@needs_ffmpeg
def test_clip_without_audio_track_is_none_and_all_mute_plan_is_empty(tmp_path):
    mute = _make_clip(tmp_path / "mute.mp4", audio=False)
    assert open_aac_track(mute) is None
    assert not plan_aac_feed([AudioSegment(mute), AudioSegment(mute)]).has_audio


@needs_ffmpeg
def test_mixed_audio_and_mute_clips_fail_instead_of_adding_silence(tmp_path):
    clip = _make_clip(tmp_path / "a.mp4")
    mute = _make_clip(tmp_path / "mute.mp4", audio=False)
    with pytest.raises(LiveMuxConfigError, match="no audio track"):
        plan_aac_feed([AudioSegment(clip), AudioSegment(mute)])


@needs_ffmpeg
def test_different_aac_formats_fail_instead_of_reencoding(tmp_path):
    a = _make_clip(tmp_path / "a.mp4", rate=48000)
    b = _make_clip(tmp_path / "b.mp4", rate=44100)
    with pytest.raises(LiveMuxConfigError, match="different AAC formats"):
        plan_aac_feed([AudioSegment(a), AudioSegment(b)])


def test_unreadable_file_is_an_error_not_missing_audio(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not an mp4 at all")
    with pytest.raises(LiveMuxConfigError):
        open_aac_track(broken)
    with pytest.raises(LiveMuxConfigError):
        open_aac_track(tmp_path / "missing.mp4")


@needs_ffmpeg
def test_segment_bounds_select_whole_aac_frames(tmp_path):
    clip = _make_clip(tmp_path / "a.mp4", seconds=6)
    track = open_aac_track(clip)
    samples = track.sample_range(2.0, 1.0)
    frame_s = 1024 / 48000
    assert abs(len(samples) * frame_s - 1.0) <= frame_s
    assert abs(samples.start * frame_s - 2.0) <= 2 * frame_s


def _ffmpeg_with_input_bsf():
    return FFMPEG if FFMPEG and ffmpeg_supports_input_bsf(FFMPEG) else None


@pytest.mark.skipif(_ffmpeg_with_input_bsf() is None, reason="needs FFmpeg 7.1+ on PATH")
def test_one_pass_mux_copies_original_aac_while_video_streams(tmp_path):
    from src.ffmpeg.live_mux_common import raw_video_timestamp_args

    clips = [_make_clip(tmp_path / f"c{i}.mp4", seconds=6, freq=440 * (i + 1)) for i in range(2)]
    encoded = tmp_path / "enc.hevc"
    if subprocess.run([
        FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30000/1001", "-t", "10",
        "-c:v", "libx265", "-x265-params", "bframes=0:log-level=error", "-f", "hevc", str(encoded),
    ]).returncode != 0:
        pytest.skip("libx265 not available")

    plan = plan_aac_feed([AudioSegment(clips[0], start_s=1.0), AudioSegment(clips[1], duration_s=5.0)])
    pipe = (rf"\\.\pipe\test_aac_{uuid.uuid4().hex}" if os.name == "nt" else str(tmp_path / "audio.fifo"))
    feeder = AacPipeFeeder(plan, pipe)
    feeder.start()
    out = tmp_path / "out.mp4"
    process = subprocess.Popen([
        FFMPEG, "-debug_ts", "-y", "-f", "hevc", "-r", "30000/1001",
        *raw_video_timestamp_args(FFMPEG, "hevc", 30000, 1001, required=True), "-i", "-",
        "-f", "aac", "-i", pipe, "-map", "0:v", "-map", "1:a:0", "-t", "10",
        "-c:v", "copy", "-c:a", "copy", "-f", "mp4", str(out),
    ], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    audio_demuxed = []
    stdin_closed = threading.Event()

    def read_stderr():
        for line in process.stderr:
            if b"demuxer -> " in line and b"type:audio" in line:
                audio_demuxed.append(stdin_closed.is_set())

    reader = threading.Thread(target=read_stderr)
    reader.start()
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
    feeder.close()

    assert feeder.error is None and feeder.completed
    assert audio_demuxed and audio_demuxed.count(False) / len(audio_demuxed) > 0.9
    expected = []
    for (track, samples), clip in zip(plan.parts, clips):
        expected += _packet_hashes(clip)[samples.start:samples.stop]
    copied = _packet_hashes(out)
    # "-t 10" may drop a final packet that starts at the cut; nothing else.
    assert copied == expected[:len(copied)] and len(expected) - len(copied) <= 1



# --- clip-boundary placement (no media files: sample tables only) ----------

GOPRO_FPS = 30000 / 1001
FRAME_S = 1024 / 48000


def _table_track(path, packets, media_time=0):
    """An AAC-LC 48 kHz stereo sample table like a GoPro audio track."""
    return AacTrack(
        path=path, timescale=48000, audio_object_type=2, sampling_index=3, channel_config=2,
        media_time=media_time, offsets=[0] * packets, sizes=[8] * packets,
        dts=[index * 1024 for index in range(packets)], audio_specific_config=b"\x11\x90",
    )


def _plan_with_tables(monkeypatch, tracks, segments):
    monkeypatch.setattr(mp4_audio_feed, "open_aac_track", lambda path: tracks[str(path)])
    return plan_aac_feed(segments)


def test_user_project_boundary_rounding_no_longer_rejects(monkeypatch):
    """Reproduces amd_child_3_1792008243239.log: 4530 + 32755 frames, clip 2 trimmed.

    Selecting each range on its own rounded both of its ends to whole AAC
    frames and the cumulative check summed those roundings (-4.3 ms after
    clip 1, then up to two more frames), rejecting a perfectly representable
    cut.  Placement must now keep every segment within half a frame.
    """
    tracks = {"GX010163.MP4": _table_track("GX010163.MP4", 7090),
              "GX010164.MP4": _table_track("GX010164.MP4", 60000)}
    segments = [AudioSegment("GX010163.MP4", 0.0, 4530 / GOPRO_FPS),
                AudioSegment("GX010164.MP4", 50.017, 32755 / GOPRO_FPS)]
    plan = _plan_with_tables(monkeypatch, tracks, segments)
    first, second = plan.placements
    assert (first.first_packet, first.packet_count) == (0, 7085)
    assert abs(first.end_residual_s) <= FRAME_S / 2
    # Clip 2 starts where clip 1's audio ended (4.3 ms early), so it starts
    # at the packet that belongs there, not at the packet nearest its IN.
    assert abs(second.sync_s) <= FRAME_S / 2
    assert abs(second.end_residual_s) <= FRAME_S / 2
    assert [samples for _track, samples in plan.parts] == [
        range(0, 7085), range(second.first_packet, second.first_packet + second.packet_count)]


def test_rounding_never_accumulates_across_many_cuts(monkeypatch):
    tracks = {"a.mp4": _table_track("a.mp4", 200000)}
    segments = [AudioSegment("a.mp4", 7.0 + index * 37.013, (91 + index * 13) / GOPRO_FPS)
                for index in range(40)]
    plan = _plan_with_tables(monkeypatch, tracks, segments)
    assert all(abs(item.sync_s) <= FRAME_S / 2 + 1e-9 for item in plan.placements)
    assert all(abs(item.end_residual_s) <= FRAME_S / 2 + 1e-9 for item in plan.placements)


def test_short_source_audio_is_compensated_from_the_next_clip_preroll(monkeypatch):
    # Clip 1 audio stops 30 ms before its video; clip 2 is trimmed, so the
    # original packets just before its IN restore sync.
    video_1 = 300 / GOPRO_FPS
    tracks = {"a.mp4": _table_track("a.mp4", round((video_1 - 0.030) / FRAME_S)),
              "b.mp4": _table_track("b.mp4", 5000)}
    plan = _plan_with_tables(monkeypatch, tracks, [AudioSegment("a.mp4", 0.0, video_1),
                                                    AudioSegment("b.mp4", 5.0, 3.0)])
    assert plan.placements[0].clamped
    assert plan.placements[0].end_residual_s < -FRAME_S
    assert abs(plan.placements[1].sync_s) <= FRAME_S / 2


def test_chapter_edge_shortfall_without_preroll_repeats_the_first_original_packet(monkeypatch):
    # GX010163 ends its audio 25.7 ms before its video and GX010164 is used
    # from IN=0: one copy of clip 2's first packet restores sync (no encoding).
    video_1 = 300 / GOPRO_FPS
    tracks = {"a.mp4": _table_track("a.mp4", round((video_1 - 0.030) / FRAME_S)),
              "b.mp4": _table_track("b.mp4", 5000)}
    plan = _plan_with_tables(monkeypatch, tracks, [AudioSegment("a.mp4", 0.0, video_1),
                                                    AudioSegment("b.mp4", 0.0, 3.0)])
    second = plan.placements[1]
    assert second.filler_packets == 1 and second.first_packet == 0
    assert abs(second.sync_s) <= FRAME_S / 2
    assert abs(second.end_residual_s) <= FRAME_S / 2
    assert "filler=1xdup_src_packet_0" in plan.report_lines()[1]


def test_filler_frames_are_copies_of_the_first_original_packet(tmp_path):
    from src.ffmpeg.mp4_audio_feed import AacFeedPlan, AacSegmentPlacement

    path = tmp_path / "t.bin"
    path.write_bytes(b"AAAABBBBCCCC")
    track = AacTrack(path=str(path), timescale=48000, audio_object_type=2, sampling_index=3,
                     channel_config=2, media_time=0, offsets=[0, 4, 8], sizes=[4, 4, 4],
                     dts=[0, 1024, 2048])
    placement = AacSegmentPlacement(str(path), 0.0, 0.0, 1.0, 0, 3, 0.0, 0.0, 1.0, 0.0, False,
                                     filler_packets=2)
    payloads = [frame[7:] for chunk in AacFeedPlan([(track, range(0, 3))], [placement]).frames()
                for frame in (chunk[i:i + 11] for i in range(0, len(chunk), 11))]
    assert payloads == [b"AAAA", b"AAAA", b"AAAA", b"BBBB", b"CCCC"]


def test_short_source_audio_beyond_filler_limit_is_a_real_offset_and_fails(monkeypatch):
    video_1 = 300 / GOPRO_FPS
    tracks = {"a.mp4": _table_track("a.mp4", round((video_1 - 0.100) / FRAME_S)),
              "b.mp4": _table_track("b.mp4", 5000)}
    with pytest.raises(LiveMuxConfigError, match=r"Segment 2 \(b.mp4\).*\+\d+\.\d ms out of sync"):
        _plan_with_tables(monkeypatch, tracks, [AudioSegment("a.mp4", 0.0, video_1),
                                                 AudioSegment("b.mp4", 0.0, 3.0)])


def test_single_range_selection_is_unchanged(monkeypatch):
    track = _table_track("a.mp4", 5000)
    plan = _plan_with_tables(monkeypatch, {"a.mp4": track}, [AudioSegment("a.mp4", 10.0, 3.003)])
    assert plan.parts[0][1] == track.sample_range(10.0, 3.003)


def _expected_copy_selection(segments, source_packets):
    """Independent oracle of the placement rule over ffprobe integer pts."""
    expected, firsts = [], []
    video_s, audio_packets = 0.0, 0
    for segment, packets in zip(segments, source_packets):
        audio_s = audio_packets * FRAME_S
        wanted = (segment.start_s + audio_s - video_s) * 48000
        if segment.start_s <= 2 and packets[0]["pts"] - wanted > 512:
            # Chapter edge without earlier packets: repeated first original packet.
            filler = int((packets[0]["pts"] - wanted) / 1024 + 0.5)
            assert filler <= 2
            expected += [packets[0]["data_hash"]] * filler
            audio_packets += filler
            audio_s = audio_packets * FRAME_S
            wanted = (segment.start_s + audio_s - video_s) * 48000
        first = min(range(len(packets)), key=lambda i: (abs(packets[i]["pts"] - wanted), -i))
        count = int(((video_s + segment.duration_s - audio_s) / FRAME_S) + 0.5)
        chosen = packets[first:first + count]
        if len(chosen) < count:
            # Only the source's own audio end may cut a segment short.
            assert segment.start_s + segment.duration_s + 2 > packets[-1]["pts"] / 48000 + 1, \
                "source window too short for the oracle"
            count = len(chosen)
        firsts.append((len(expected), chosen[0]["pts"] / 48000, audio_s, video_s, segment.start_s))
        expected += [p["data_hash"] for p in chosen]
        audio_packets += count
        video_s += segment.duration_s
    return expected, firsts


@pytest.mark.skipif(os.name != "nt", reason="Windows named pipe contract")
@pytest.mark.parametrize("reader", [False, True])
def test_windows_pipe_cancellation_releases_blocked_writer(tmp_path, reader):
    import ctypes
    from ctypes import wintypes

    class LargePlan:
        def frames(self):
            while True:
                yield b"x" * (2 << 20)

    pipe = rf"\\.\pipe\aac_abort_{uuid.uuid4().hex}"
    feeder = AacPipeFeeder(LargePlan(), pipe)
    feeder.start()
    client = None
    if reader:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        client = kernel.CreateFileW(pipe, 0x80000000, 0, None, 3, 0, None)
        assert client not in (None, ctypes.c_void_p(-1).value)
    time.sleep(0.1)
    began = time.monotonic()
    try:
        feeder.close(timeout=2)
        assert not feeder._thread.is_alive()
        assert time.monotonic() - began < 2
    finally:
        if client:
            kernel.CloseHandle(client)


@pytest.mark.skipif(
    os.name != "nt" or os.getenv("SPORTCAMHUD_REAL_GOPRO_COPY") != "1",
    reason="explicit Windows/original GoPro integration run",
)
@pytest.mark.parametrize("case", ["single_trim", "multi_trim", "pause_cuts", "user_boundary", "chapter_edge"])
def test_real_gopro_native_copy_packets_and_live_mux(case, monkeypatch, capsys):
    """Existing native exporter seam, short ranges, actual DLL and original MP4s."""
    from pathlib import Path
    from src.multifile import VideoClip, VideoTimeline
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

    root = Path(__file__).resolve().parents[1]
    ffmpeg = str(root / "runtime/common/ffmpeg/ffmpeg.exe")
    ffprobe = str(root / "runtime/common/ffmpeg/ffprobe.exe")
    a = r"F:\GoPro\2026-10-07\GX010350.MP4"
    b = r"F:\GoPro\2026-10-12\GX010366.MP4"
    # No FIT is used: this verifies mux/packet/timestamp contracts, not HUD.
    fps = 30000 / 1001
    span = 90 / fps
    segments = [AudioSegment(a, 10.0, span)]
    if case == "multi_trim":
        segments.append(AudioSegment(b, 20.0, span))
    if case == "pause_cuts":
        segments.append(AudioSegment(a, 25.0, span))
    if case == "user_boundary":
        # The failed user project (amd_child_3_1792008243239.log): the last
        # 90 frames of the whole GX010163 and 90 frames of GX010164 at a
        # trimmed IN that does not fall on an AAC frame.
        segments = [AudioSegment(USER_CLIP_1, (4530 - 90) / fps, span),
                    AudioSegment(USER_CLIP_2, 50.017, span)]
    if case == "chapter_edge":
        # Contiguous chapters: GX010163's audio ends 25.7 ms before its video
        # and GX010164 starts at IN=0, so no earlier packet exists.
        segments = [AudioSegment(USER_CLIP_1, (4530 - 90) / fps, span),
                    AudioSegment(USER_CLIP_2, 0.0, span)]
    timeline = VideoTimeline([
        VideoClip(path=Path(s.path), duration_s=s.duration_s, local_start_s=s.start_s,
                  source_duration_s=3000.0, fps=fps, width=3840, height=2160)
        for s in segments
    ])
    folder = root / "Raporty/direct_copy_audio_boundary_fix" / f"{case}_{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    output = folder / "final.mp4"
    monkeypatch.setenv("TELEM_RENDER_DEBUG", "1")
    monkeypatch.delenv("TELEM_MAX_FRAMES", raising=False)
    monkeypatch.setenv("AMD_DIRECT_MUX", "1")
    monkeypatch.setenv("AMD_SINGLE_PASS_AV_MUX", "1")
    monkeypatch.delenv("AMD_DIRECT_MUX_NO_AUDIO", raising=False)
    actual_popen = subprocess.Popen
    observed = {"audio_before_eof": 0, "audio_after_eof": 0, "commands": []}
    eof = threading.Event()
    from src.ffmpeg import mp4_audio_feed
    original_plan = mp4_audio_feed.plan_aac_feed
    def observed_plan(selected_segments):
        plan = original_plan(selected_segments)
        original_frames = plan.frames
        def frames():
            for data in original_frames():
                key = "source_read_chunks_after_eof" if eof.is_set() else "source_read_chunks_before_eof"
                observed[key] = observed.get(key, 0) + 1
                yield data
            observed["source_read_complete_monotonic"] = time.monotonic()
        plan.frames = frames
        return plan
    monkeypatch.setattr(mp4_audio_feed, "plan_aac_feed", observed_plan)

    class StdinObserver:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def close(self):
            observed["stdin_eof_monotonic"] = time.monotonic()
            eof.set()
            return self.stream.close()

    class StderrObserver:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def __iter__(self):
            for line in self.stream:
                if b"demuxer ->" in line and b"type:audio" in line:
                    key = "audio_after_eof" if eof.is_set() else "audio_before_eof"
                    observed[key] += 1
                yield line

    def watch_popen(command, *args, **kwargs):
        is_mux = kwargs.get("stdin") == subprocess.PIPE and "hevc" in command
        if is_mux:
            command = [command[0], "-debug_ts", *command[1:]]
        proc = actual_popen(command, *args, **kwargs)
        if is_mux:
            observed["commands"].append(command)
            observed["ffmpeg_pid"] = proc.pid
            proc.stdin = StdinObserver(proc.stdin)
            proc.stderr = StderrObserver(proc.stderr)
            real_poll = proc.poll
            def poll():
                code = real_poll()
                if code is not None:
                    observed.setdefault("ffmpeg_exit_monotonic", time.monotonic())
                return code
            proc.poll = poll
        return proc

    monkeypatch.setattr(subprocess, "Popen", watch_popen)
    success = export_amd_native_d3d11(
        ffmpeg_exe=ffmpeg, input_files=list(dict.fromkeys(s.path for s in segments)),
        output_file=str(output), duration_s=span * len(segments), video_width=1280, video_height=720,
        start_dt_utc=None, tz_offset_hours=0.0, speed_samples=[], track_samples=[], alt_samples=[],
        font_path="", layout={}, field_samples={}, target_fps=fps,
        video_bitrate="5M", quality={"single_trim": "FAST", "multi_trim": "BALANCED", "pause_cuts": "QUALITY",
                 "user_boundary": "BALANCED", "chapter_edge": "BALANCED"}[case],
        video_timeline=timeline,
    )
    observed["export_return_monotonic"] = time.monotonic()
    (folder / "export.log").write_text(capsys.readouterr().out, encoding="utf-8")
    assert success
    assert len(observed["commands"]) == 1
    command = observed["commands"][0]
    assert command[command.index("-c") + 1] == "copy"
    assert "-filter_complex" not in command and "-b:a" not in command

    def packets(path, interval=None):
        cmd = [ffprobe, "-v", "error", "-select_streams", "a:0"]
        if interval:
            cmd += ["-read_intervals", interval]
        cmd += ["-show_packets", "-show_data_hash", "sha256", "-show_entries",
                "packet=pts,dts,duration,pts_time,dts_time,duration_time,data_hash", "-of", "json", str(path)]
        return json.loads(subprocess.check_output(cmd, text=True))["packets"]

    final = packets(output)
    source_windows = [packets(segment.path, f"{max(0, segment.start_s - 2)}%+{span + 4}")
                      for segment in segments]
    expected, firsts = _expected_copy_selection(segments, source_windows)
    boundaries = [index for index, *_rest in firsts[1:]] + [len(expected)]
    hashes = [p["data_hash"] for p in final]
    assert hashes == expected, "AAC loss/change/duplicate at selected ranges or clip boundary"
    pts = [float(p["pts_time"]) for p in final]
    dts = [float(p["dts_time"]) for p in final]
    packet_s = 1024 / 48000
    assert all(abs(p - d) < 1e-6 for p, d in zip(pts, dts))
    assert all(abs(b - a - packet_s) < 2e-6 for a, b in zip(dts, dts[1:]))
    assert abs(pts[0]) <= packet_s
    sync_ms = []
    for out_index, source_s, audio_s, video_s, in_s in firsts:
        assert abs(pts[out_index] - audio_s) < 2e-6
        sync_ms.append((source_s - (in_s + audio_s - video_s)) * 1000)
    assert all(abs(value) <= packet_s * 500 + 1e-3 for value in sync_ms), sync_ms
    assert observed["audio_before_eof"] > 0
    assert observed.get("source_read_chunks_after_eof", 0) == 0
    assert observed["source_read_complete_monotonic"] <= observed["stdin_eof_monotonic"]
    assert observed["audio_before_eof"] / (
        observed["audio_before_eof"] + observed["audio_after_eof"]
    ) > 0.9, "audio demux was deferred to finalization (existing harness contract)"
    profile = json.loads(Path(str(output) + ".amd_profile.json").read_text())
    video = next(stream for stream in profile["output"]["streams"] if stream["codec_type"] == "video")
    assert abs(float(video["duration"]) - span * len(segments)) < 1e-5
    observed.update({
        "case": case, "sources": [s.__dict__ for s in segments],
        "aac_packets": len(hashes), "packet_parity": True,
        "audio_first_pts": pts[0], "audio_end_pts": pts[-1] + packet_s,
        "boundary_packet_counts": boundaries,
        "source_selected_sha256": expected,
        "final_aac_sha256": hashes,
        "aac_boundary_end_residual_ms": [(pts[count - 1] + packet_s - span * (i + 1)) * 1000
                                         for i, count in enumerate(boundaries)],
        "aac_segment_sync_ms": sync_ms,
        "video_duration_s": float(video["duration"]),
        "ffmpeg_exit_after_stdin_eof_ms": (observed["ffmpeg_exit_monotonic"] -
                                            observed["stdin_eof_monotonic"]) * 1000,
        "finalization_ms": profile["etap8p_a"]["mux_wall_ms"],
        "profile": str(output) + ".amd_profile.json",
    })
    (folder / "evidence.json").write_text(json.dumps(observed, indent=2), encoding="utf-8")


USER_CLIP_1 = r"F:\GoPro\2026-08-27\GX010163.MP4"
USER_CLIP_2 = r"F:\GoPro\2026-08-27\GX010164.MP4"


@pytest.mark.skipif(
    not (os.path.exists(USER_CLIP_1) and os.path.exists(USER_CLIP_2)),
    reason="original GoPro files of the failed user project",
)
@pytest.mark.parametrize("clip_2_in", [0.0, 50.017, 103.5])
def test_user_project_real_sample_tables_plan(clip_2_in):
    """Segmentation only, on the real sample tables (no video is read)."""
    from pathlib import Path

    fps = 30000 / 1001
    segments = [AudioSegment(USER_CLIP_1, 0.0, 4530 / fps),
                AudioSegment(USER_CLIP_2, clip_2_in, 32755 / fps)]
    tracks = [open_aac_track(path) for path in (USER_CLIP_1, USER_CLIP_2)]
    plan = plan_aac_feed(segments)
    report = {
        "segments": [s.__dict__ for s in segments],
        "source_audio": [{"path": t.path, "packets": len(t.sizes), "media_time": t.media_time,
                          "duration_s": (t.dts[-1] + 1024 - t.media_time) / t.timescale} for t in tracks],
        "placements": [dict(p.__dict__, end_residual_s=p.end_residual_s) for p in plan.placements],
        "report_lines": plan.report_lines(),
    }
    folder = Path(__file__).resolve().parents[1] / "Raporty/direct_copy_audio_boundary_fix"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"user_plan_in_{clip_2_in:g}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    frame_s = 1024 / 48000
    assert all(abs(p.sync_s) <= frame_s / 2 + 1e-9 or p.clamped for p in plan.placements)
    assert all(abs(p.sync_s) <= frame_s + 1e-9 for p in plan.placements)
