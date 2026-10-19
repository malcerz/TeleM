"""Backend-neutral helpers for the single-pass live A/V mux.

Every native exporter (AMD, NVIDIA, Intel) streams an encoded elementary
video bitstream into FFmpeg stdin and asks the same FFmpeg process to add the
source audio.  Two FFmpeg behaviours turned that "single pass" into a hidden
second pass on multi-file exports:

1. A raw ``-f hevc`` / ``-f h264`` stdin stream carries no timestamps.  The
   FFmpeg scheduler always feeds the output stream with the smallest DTS, and a
   stream whose DTS is unknown wins forever, so the audio input is starved for
   the whole encode and read only after stdin closes ("finalizing").
   ``raw_video_timestamp_args`` assigns CFR timestamps on the input side with
   the ``setts`` bitstream filter, so audio is demuxed and interleaved live.

2. The concat demuxer does not pass stream discard down to the per-file MP4
   demuxer, so taking audio from ``-f concat`` reads every 4K video packet of
   every source clip.  ``build_live_audio_inputs`` opens each clip segment as
   its own MP4 input instead (the MP4 demuxer skips discarded video samples)
   and joins the segments with the ``concat`` audio filter.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence

# Codec-neutral pieces live in live_mux_common (the AMD direct-copy path uses
# only that module); they are re-exported here for the Intel/NVIDIA callers.
from src.ffmpeg.live_mux_common import (  # noqa: F401
    AudioSegment,
    LiveAudioInputs,
    LiveMuxConfigError,
    audio_segments_from_timeline,
    ffmpeg_supports_input_bsf,
    raw_video_timestamp_args,
)

# Re-encode bitrate for joined multi-segment audio (GoPro sources are
# ~256 kb/s AAC).  Single-segment audio is still stream-copied.
LIVE_AUDIO_AAC_BITRATE = "256k"


def probe_has_audio(ffprobe_exe: str, media_path: str | Path) -> bool:
    """True when ``media_path`` has at least one audio stream."""
    command = [
        ffprobe_exe, "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "json",
        str(media_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return bool(json.loads(result.stdout or "{}").get("streams"))
    except Exception:
        pass
    return False


def probe_audio_present(ffprobe_exe: str, media_path: str | Path) -> bool:
    """Like ``probe_has_audio``, but a failed probe raises instead of meaning "no audio"."""
    command = [
        ffprobe_exe, "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "json",
        str(media_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        raise LiveMuxConfigError(f"ffprobe failed for {media_path}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[-300:]
        raise LiveMuxConfigError(
            f"ffprobe failed for {media_path} (rc={result.returncode}): {detail}"
        )
    try:
        streams = json.loads(result.stdout or "{}").get("streams")
    except ValueError as exc:
        raise LiveMuxConfigError(f"ffprobe returned invalid JSON for {media_path}") from exc
    return bool(streams)


def probe_duration(ffprobe_exe: str, media_path: str | Path) -> float:
    """Container duration in seconds, or 0.0 when it cannot be probed."""
    command = [
        ffprobe_exe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return float((result.stdout or "0").strip() or 0.0)
    except Exception:
        pass
    return 0.0


def build_live_audio_inputs(
    segments: Sequence[AudioSegment],
    first_input_index: int,
    *,
    ffprobe_exe: str = "ffprobe",
    has_audio: Optional[Callable[[str], bool]] = None,
    thread_queue_size: Optional[int] = None,
    strict: bool = False,
) -> LiveAudioInputs:
    """Audio inputs, mapping and codec args for a single-pass live mux.

    ``first_input_index`` is the FFmpeg input index the first audio input will
    get (1 when the video pipe is input 0).  Inputs that follow the audio, such
    as an inline GPMF track, start at ``first_input_index + input_count``.

    With ``strict=True`` a failed ffprobe raises ``LiveMuxConfigError`` instead
    of being treated as a clip without audio.
    """
    segments = [segment for segment in segments if segment.path]
    if not segments:
        return LiveAudioInputs()

    queue_args = ["-thread_queue_size", str(thread_queue_size)] if thread_queue_size else []

    def _source_input(segment: AudioSegment) -> list[str]:
        args = list(queue_args)
        if segment.duration_s is not None:
            args += ["-t", f"{segment.duration_s:.6f}"]
        if segment.start_s > 1e-6:
            args += ["-ss", f"{segment.start_s:.6f}"]
        return args + ["-i", segment.path]

    if len(segments) == 1:
        # One source range: keep the original AAC bit-exact.  The optional
        # map makes a source without audio produce a video-only file.
        return LiveAudioInputs(
            input_args=_source_input(segments[0]),
            map_args=["-map", f"{first_input_index}:a:0?"],
            codec_args=["-c:a", "copy"],
            input_count=1,
            mode="copy",
        )

    default_probe = probe_audio_present if strict else probe_has_audio
    probe = has_audio or (lambda path: default_probe(ffprobe_exe, path))
    audio_by_path: dict[str, bool] = {}
    for segment in segments:
        if segment.path not in audio_by_path:
            audio_by_path[segment.path] = probe(segment.path)
    if not any(audio_by_path.values()):
        return LiveAudioInputs()

    input_args: list[str] = []
    labels: list[str] = []
    for ordinal, segment in enumerate(segments):
        index = first_input_index + ordinal
        if audio_by_path[segment.path]:
            input_args += _source_input(segment)
        else:
            # Keep A/V sync across a clip without audio.
            silence_s = segment.duration_s
            if silence_s is None:
                silence_s = max(0.0, probe_duration(ffprobe_exe, segment.path) - segment.start_s)
                if strict and silence_s <= 0.0:
                    raise LiveMuxConfigError(
                        f"cannot determine the length of {segment.path}, which has no audio"
                    )
            input_args += [
                "-f", "lavfi", "-t", f"{silence_s:.6f}",
                "-i", "anullsrc=r=48000:cl=stereo",
            ]
        labels.append(f"[{index}:a:0]")
    graph = "".join(labels) + f"concat=n={len(segments)}:v=0:a=1[aout]"
    return LiveAudioInputs(
        input_args=input_args,
        map_args=["-filter_complex", graph, "-map", "[aout]"],
        codec_args=["-c:a", "aac", "-b:a", LIVE_AUDIO_AAC_BITRATE],
        input_count=len(segments),
        mode="concat_filter",
    )
