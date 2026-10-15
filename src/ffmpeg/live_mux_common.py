"""Shared, codec-neutral pieces of the single-pass live A/V mux.

This module holds only what every live mux path needs to describe audio
ranges and give a raw stdin video bitstream timestamps.  It contains no audio
encoding: the AMD direct-copy path depends on this module alone, while the
re-encoding helpers used by other backends stay in ``live_av_mux``.
"""

from __future__ import annotations

import functools
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional

_RAW_VIDEO_FORMATS_WITHOUT_TIMESTAMPS = {"hevc", "h264", "obu"}


class LiveMuxConfigError(RuntimeError):
    """The live mux cannot be configured correctly; never fall back silently."""


@dataclass(frozen=True)
class AudioSegment:
    """One source-local audio range on the export timeline."""

    path: str
    start_s: float = 0.0
    # None means "until the end of the source file".
    duration_s: Optional[float] = None


@dataclass
class LiveAudioInputs:
    """FFmpeg argument groups for the audio part of a live mux command."""

    input_args: list[str] = field(default_factory=list)
    map_args: list[str] = field(default_factory=list)
    codec_args: list[str] = field(default_factory=list)
    input_count: int = 0
    mode: str = "none"  # none | copy | concat_filter | aac_pipe_copy

    @property
    def has_audio(self) -> bool:
        return self.mode != "none"


@functools.lru_cache(maxsize=8)
def ffmpeg_supports_input_bsf(ffmpeg_exe: str) -> bool:
    """True when this FFmpeg build accepts ``-bsf`` as an input option (7.1+)."""
    command = [
        ffmpeg_exe, "-hide_banner", "-nostdin", "-v", "error",
        "-bsf:v", "null",
        "-f", "lavfi", "-i", "color=s=16x16:r=1:d=1",
        "-frames:v", "1", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False
    return result.returncode == 0


def raw_video_timestamp_args(
    ffmpeg_exe: str,
    raw_format: str,
    fps_num: int,
    fps_den: int,
    *,
    required: bool = False,
) -> list[str]:
    """Input options that give a raw stdin bitstream CFR timestamps.

    Place the result immediately before ``-i -``.  The native encoders emit no
    B-frames (and AV1 temporal units are never reordered), so decode order
    equals presentation order and pts = dts = N.
    These are the same timestamps the MP4 muxer synthesised before; the
    difference is that the FFmpeg scheduler now sees them too.

    With ``required=True`` a build without input ``-bsf`` support raises
    ``LiveMuxConfigError`` instead of returning an untimed configuration.
    """
    if raw_format not in _RAW_VIDEO_FORMATS_WITHOUT_TIMESTAMPS:
        return []
    if fps_num <= 0 or fps_den <= 0:
        return []
    if not ffmpeg_supports_input_bsf(ffmpeg_exe):
        if required:
            raise LiveMuxConfigError(
                f"{ffmpeg_exe} does not support input -bsf (FFmpeg 7.1+ required); "
                "without timestamps the audio would be read only after the video ends"
            )
        print(
            f"[LIVE AV MUX] WARNING: {ffmpeg_exe} does not support input -bsf; "
            "audio will be muxed after the video stream ends",
            flush=True,
        )
        return []
    frame = f"{int(fps_den)}/{int(fps_num)}/TB"
    return ["-bsf:v", f"setts=ts=N*{frame}:duration={frame}"]


def audio_segments_from_timeline(video_timeline: Any) -> list[AudioSegment]:
    """Source-local audio ranges matching a GUI/cut-resolved VideoTimeline."""
    segments: list[AudioSegment] = []
    for clip in list(getattr(video_timeline, "clips", ()) or ()):
        start = float(getattr(clip, "local_start_s", 0.0) or 0.0)
        duration = float(getattr(clip, "duration_s", 0.0) or 0.0)
        source_duration = float(getattr(clip, "source_duration_s", 0.0) or 0.0)
        reaches_end = source_duration > 0.0 and start + duration >= source_duration - 1e-6
        segments.append(
            AudioSegment(
                path=str(clip.path),
                start_s=max(0.0, start),
                duration_s=None if (reaches_end or duration <= 0.0) else duration,
            )
        )
    return segments
