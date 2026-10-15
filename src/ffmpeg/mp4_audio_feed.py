"""Lossless multi-clip AAC feed for the single-pass live mux.

Joining the audio of several MP4 clips with FFmpeg's concat demuxer reads
every video packet of every clip (8.6 GB for 37 MB of audio on a 4K GoPro
pair), and the concat filter re-encodes.  This module reads only the AAC
samples straight from each clip's MP4 sample tables, prefixes each with an
ADTS header and streams them through a pipe into the same FFmpeg process that
muxes the live video (``-f aac -i <pipe> -c:a copy``).  The AAC payloads
reach the output byte-for-byte; no file, extra process or second pass.
"""

from __future__ import annotations

import os
import math
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterator, Optional, Sequence

from src.ffmpeg.live_mux_common import AudioSegment, LiveMuxConfigError

_CONTAINER_BOXES = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}
# Contiguous sample runs are read in one go up to this size.
_MAX_READ_BYTES = 1 << 20
# Repeated original packets allowed in front of a clip whose predecessor's
# audio ends before its video (GoPro chapter edge); more is a real gap.
_MAX_FILLER_PACKETS = 2


@dataclass
class AacTrack:
    """The first AAC audio track of an MP4 file, as sample tables."""

    path: str
    timescale: int
    audio_object_type: int
    sampling_index: int
    channel_config: int
    media_time: int
    offsets: list[int]
    sizes: list[int]
    dts: list[int]
    audio_specific_config: bytes = b""

    @property
    def stream_format(self) -> tuple[int, int, int, bytes]:
        return (self.audio_object_type, self.sampling_index, self.channel_config, self.audio_specific_config)

    def sample_range(self, start_s: float, duration_s: Optional[float]) -> range:
        """Samples whose midpoint lies in [start_s, start_s + duration_s)."""
        count = len(self.sizes)
        if count == 0:
            return range(0)
        start_ts = start_s * self.timescale + self.media_time
        end_ts = None if duration_s is None else (start_s + duration_s) * self.timescale + self.media_time
        first = count
        last = count
        for index in range(count):
            next_dts = self.dts[index + 1] if index + 1 < count else self.dts[index] + 1024
            mid = (self.dts[index] + next_dts) / 2.0
            if first == count and mid >= start_ts:
                first = index
            if end_ts is not None and mid >= end_ts:
                last = index
                break
        return range(first, max(first, last))


def _boxes(handle: BinaryIO, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    """Yield (type, payload_start, box_end) for boxes in [start, end)."""
    position = start
    while position + 8 <= end:
        handle.seek(position)
        header = handle.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        payload = position + 8
        if size == 1:
            size = struct.unpack(">Q", handle.read(8))[0]
            payload += 8
        elif size == 0:
            size = end - position
        if size < 8:
            return
        yield kind, payload, position + size
        position += size


def _find(handle: BinaryIO, start: int, end: int, path: Sequence[bytes]) -> list[tuple[int, int]]:
    """All (payload_start, end) of boxes matching a nested type path."""
    found: list[tuple[int, int]] = []
    for kind, payload, box_end in _boxes(handle, start, end):
        if kind != path[0]:
            continue
        if len(path) == 1:
            found.append((payload, box_end))
        elif kind in _CONTAINER_BOXES:
            found.extend(_find(handle, payload, box_end, path[1:]))
    return found


def _read(handle: BinaryIO, payload: int, end: int) -> bytes:
    handle.seek(payload)
    return handle.read(end - payload)


def _descriptor(data: bytes, offset: int) -> tuple[int, int, int]:
    """Parse an MPEG-4 descriptor header: (tag, body_start, body_end)."""
    tag = data[offset]
    offset += 1
    length = 0
    for _ in range(4):
        byte = data[offset]
        offset += 1
        length = (length << 7) | (byte & 0x7F)
        if not byte & 0x80:
            break
    return tag, offset, offset + length


def _audio_specific_config(esds: bytes) -> bytes:
    tag, body, end = _descriptor(esds, 4)  # skip version/flags
    if tag != 0x03:
        raise ValueError("esds without ES_Descriptor")
    flags = esds[body + 2]
    body += 3
    if flags & 0x80:
        body += 2
    if flags & 0x40:
        body += 1 + esds[body]
    if flags & 0x20:
        body += 2
    tag, body, end = _descriptor(esds, body)
    if tag != 0x04:
        raise ValueError("esds without DecoderConfigDescriptor")
    tag, body, end = _descriptor(esds, body + 13)
    if tag != 0x05:
        raise ValueError("esds without DecoderSpecificInfo")
    return esds[body:end]


def _parse_track(handle: BinaryIO, path: str, trak: tuple[int, int]) -> Optional[AacTrack]:
    hdlr = _find(handle, trak[0], trak[1], [b"mdia", b"hdlr"])
    if not hdlr or _read(handle, *hdlr[0])[8:12] != b"soun":
        return None
    stsd = _read(handle, *_find(handle, trak[0], trak[1], [b"mdia", b"minf", b"stbl", b"stsd"])[0])
    entry = stsd[8:]
    if entry[4:8] != b"mp4a":
        raise LiveMuxConfigError(f"{path}: audio is {entry[4:8]!r}, not AAC")
    version = struct.unpack(">H", entry[16:18])[0]
    child = 8 + 28 + {0: 0, 1: 16, 2: 36}.get(version, 0)
    asc = None
    entry_size = struct.unpack(">I", entry[:4])[0]
    while child + 8 <= entry_size:
        size, kind = struct.unpack(">I4s", entry[child:child + 8])
        if kind == b"esds":
            asc = _audio_specific_config(entry[child + 8:child + size])
            break
        if size < 8:
            break
        child += size
    if not asc or len(asc) < 2:
        raise LiveMuxConfigError(f"{path}: AAC track without AudioSpecificConfig")
    object_type = asc[0] >> 3
    sampling_index = ((asc[0] & 0x07) << 1) | (asc[1] >> 7)
    channel_config = (asc[1] >> 3) & 0x0F
    # ADTS cannot retain arbitrary ASC extensions or 960-sample frames.
    if object_type != 2 or sampling_index >= 13 or not 1 <= channel_config <= 7 or asc[1] & 0x07 or (
        asc[2:].strip(b"\x00") and asc[2:] != b"\x56\xe5\x00"  # padding or explicitly absent SBR
    ):
        raise LiveMuxConfigError(
            f"{path}: AAC object type {object_type}/rate index {sampling_index}/"
            f"channels {channel_config} cannot be carried as ADTS"
        )

    mdhd = _read(handle, *_find(handle, trak[0], trak[1], [b"mdia", b"mdhd"])[0])
    timescale = struct.unpack(">I", mdhd[20:24] if mdhd[0] == 1 else mdhd[12:16])[0]

    media_time = 0
    elst = _find(handle, trak[0], trak[1], [b"edts", b"elst"])
    if elst:
        data = _read(handle, *elst[0])
        entries = struct.unpack(">I", data[4:8])[0]
        if entries != 1:
            raise LiveMuxConfigError(f"{path}: complex AAC edit list cannot be preserved by the lossless pipe")
        width = 20 if data[0] == 1 else 12
        for index in range(entries):
            row = data[8 + index * width:8 + (index + 1) * width]
            value = struct.unpack(">q", row[8:16])[0] if data[0] == 1 else struct.unpack(">i", row[4:8])[0]
            if value < 0 or row[-4:] != b"\x00\x01\x00\x00":
                raise LiveMuxConfigError(f"{path}: AAC edit delay/rate cannot be preserved by the lossless pipe")
            if value >= 0:
                media_time = value
                break

    stbl = _find(handle, trak[0], trak[1], [b"mdia", b"minf", b"stbl"])[0]
    tables = {kind: (payload, end) for kind, payload, end in _boxes(handle, *stbl)}
    if b"ctts" in tables:
        raise LiveMuxConfigError(f"{path}: AAC composition offsets require a timestamped transport")

    data = _read(handle, *tables[b"stsz"])
    uniform, count = struct.unpack(">II", data[4:12])
    sizes = [uniform] * count if uniform else list(struct.unpack(f">{count}I", data[12:12 + 4 * count]))

    if b"stco" in tables:
        data = _read(handle, *tables[b"stco"])
        chunks = struct.unpack(">I", data[4:8])[0]
        chunk_offsets = list(struct.unpack(f">{chunks}I", data[8:8 + 4 * chunks]))
    else:
        data = _read(handle, *tables[b"co64"])
        chunks = struct.unpack(">I", data[4:8])[0]
        chunk_offsets = list(struct.unpack(f">{chunks}Q", data[8:8 + 8 * chunks]))

    data = _read(handle, *tables[b"stsc"])
    runs = struct.unpack(">I", data[4:8])[0]
    stsc = [struct.unpack(">III", data[8 + 12 * i:20 + 12 * i]) for i in range(runs)]
    offsets: list[int] = []
    for run, (first_chunk, per_chunk, _desc) in enumerate(stsc):
        if _desc != 1:
            raise LiveMuxConfigError(f"{path}: AAC sample description changes within the clip")
        last_chunk = stsc[run + 1][0] - 1 if run + 1 < len(stsc) else len(chunk_offsets)
        for chunk in range(first_chunk, last_chunk + 1):
            position = chunk_offsets[chunk - 1]
            for _ in range(per_chunk):
                if len(offsets) >= count:
                    break
                offsets.append(position)
                position += sizes[len(offsets) - 1]
    if len(offsets) != count:
        raise LiveMuxConfigError(f"{path}: AAC sample tables are inconsistent")

    data = _read(handle, *tables[b"stts"])
    runs = struct.unpack(">I", data[4:8])[0]
    dts: list[int] = []
    clock = 0
    for i in range(runs):
        run_count, delta = struct.unpack(">II", data[8 + 8 * i:16 + 8 * i])
        for _ in range(run_count):
            dts.append(clock)
            clock += delta
    dts = dts[:count]
    sample_rates = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)
    if timescale != sample_rates[sampling_index] or len(dts) != count or any(
        b - a != 1024 for a, b in zip(dts, dts[1:])
    ):
        raise LiveMuxConfigError(f"{path}: AAC timing cannot be preserved by the lossless pipe")
    if any(size <= 0 or size + 7 > 8191 for size in sizes):
        raise LiveMuxConfigError(f"{path}: AAC packet cannot fit lossless ADTS transport")

    return AacTrack(
        path=path,
        timescale=timescale,
        audio_object_type=object_type,
        sampling_index=sampling_index,
        channel_config=channel_config,
        media_time=media_time,
        offsets=offsets,
        sizes=sizes,
        dts=dts,
        audio_specific_config=asc,
    )


def open_aac_track(path: str | Path) -> Optional[AacTrack]:
    """Sample tables of the first audio track, or None when the file has no audio.

    Raises ``LiveMuxConfigError`` when the file cannot be read or its audio is
    not AAC that ADTS can carry; an unreadable file is never "no audio".
    """
    path = str(path)
    try:
        with open(path, "rb") as handle:
            end = handle.seek(0, os.SEEK_END)
            moov = _find(handle, 0, end, [b"moov"])
            if not moov:
                raise LiveMuxConfigError(f"{path}: no moov box (not a complete MP4)")
            for trak in _find(handle, moov[0][0], moov[0][1], [b"trak"]):
                track = _parse_track(handle, path, trak)
                if track is not None:
                    return track
    except LiveMuxConfigError:
        raise
    except (OSError, ValueError, struct.error, KeyError, IndexError) as exc:
        raise LiveMuxConfigError(f"{path}: cannot read MP4 audio tables: {exc}") from exc
    return None


def _adts_header(track: AacTrack, payload_size: int) -> bytes:
    length = payload_size + 7
    return bytes((
        0xFF,
        0xF1,
        ((track.audio_object_type - 1) << 6) | (track.sampling_index << 2) | (track.channel_config >> 2),
        ((track.channel_config & 0x03) << 6) | (length >> 11),
        (length >> 3) & 0xFF,
        ((length & 0x07) << 5) | 0x1F,
        0xFC,
    ))


def iter_adts(track: AacTrack, samples: range) -> Iterator[bytes]:
    """ADTS frames for ``samples``, reading contiguous sample runs at once."""
    with open(track.path, "rb") as handle:
        index = samples.start
        while index < samples.stop:
            run_end = index + 1
            run_bytes = track.sizes[index]
            while (
                run_end < samples.stop
                and track.offsets[run_end] == track.offsets[run_end - 1] + track.sizes[run_end - 1]
                and run_bytes + track.sizes[run_end] <= _MAX_READ_BYTES
            ):
                run_bytes += track.sizes[run_end]
                run_end += 1
            handle.seek(track.offsets[index])
            block = handle.read(run_bytes)
            if len(block) != run_bytes:
                raise LiveMuxConfigError(f"{track.path}: truncated AAC data")
            frames = []
            position = 0
            for sample in range(index, run_end):
                size = track.sizes[sample]
                frames.append(_adts_header(track, size))
                frames.append(block[position:position + size])
                position += size
            yield b"".join(frames)
            index = run_end


@dataclass(frozen=True)
class AacSegmentPlacement:
    """Where one segment's copied AAC packets land relative to its video.

    All times are seconds.  ``video_*`` is the export timeline of the segment,
    ``audio_*`` where its copied packets land on that timeline.  ``sync_s`` is
    the constant A/V offset inside the segment (> 0: audio leads the video).
    """

    path: str
    source_in_s: float
    video_start_s: float
    video_end_s: float
    first_packet: int
    packet_count: int
    first_packet_source_s: float
    audio_start_s: float
    audio_end_s: float
    sync_s: float
    clamped: bool
    filler_packets: int = 0

    @property
    def end_residual_s(self) -> float:
        return self.audio_end_s - self.video_end_s


@dataclass
class AacFeedPlan:
    """Resolved per-segment sample ranges; empty ``parts`` means no audio."""

    parts: list[tuple[AacTrack, range]]
    placements: list[AacSegmentPlacement] = field(default_factory=list)

    @property
    def has_audio(self) -> bool:
        return bool(self.parts)

    def frames(self) -> Iterator[bytes]:
        for index, (track, samples) in enumerate(self.parts):
            filler = self.placements[index].filler_packets if index < len(self.placements) else 0
            if filler and samples:
                first = b"".join(iter_adts(track, range(samples.start, samples.start + 1)))
                yield first * filler
            yield from iter_adts(track, samples)

    def report_lines(self) -> list[str]:
        lines = []
        for index, item in enumerate(self.placements, 1):
            lines.append(
                f"seg={index} src={Path(item.path).name} in={item.source_in_s:.6f} "
                f"video=[{item.video_start_s:.6f},{item.video_end_s:.6f}) "
                f"packets={item.first_packet}+{item.packet_count} "
                f"first_src={item.first_packet_source_s:.6f} "
                f"audio=[{item.audio_start_s:.6f},{item.audio_end_s:.6f}) "
                f"sync_ms={item.sync_s * 1000:+.3f} end_residual_ms={item.end_residual_s * 1000:+.3f}"
                + (" clamped=source_edge" if item.clamped else "")
                + (f" filler={item.filler_packets}xdup_src_packet_{item.first_packet}"
                   if item.filler_packets else "")
            )
        return lines


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _place_segments(
    segments: Sequence[AudioSegment], tracks: dict[str, AacTrack]
) -> tuple[list[tuple[AacTrack, range]], list[AacSegmentPlacement]]:
    """Choose whole AAC packets so every segment stays in sync with its video.

    The copied packets form one gapless stream, so a segment's packets start
    wherever the previous segment's packets ended, not exactly at its video
    start.  Each segment therefore starts at the source packet nearest to the
    source time that belongs at that audio position, and takes the packet
    count that ends nearest to its video end.  Rounding then never
    accumulates: the offset stays within half an AAC frame per segment.  Only
    a source whose audio is missing at a needed edge can exceed that, and
    that is reported as a real offset, not hidden.

    One exception: GoPro chapters end their audio up to about one frame
    before their video (GX010163: 25.7 ms), and a following clip used from
    its very start has no earlier packets to restore sync.  Up to
    ``_MAX_FILLER_PACKETS`` copies of that clip's first original packet are
    then repeated in front of it (copied bytes, nothing encoded); a larger
    shortfall is still a real gap and fails.
    """
    parts: list[tuple[AacTrack, range]] = []
    placements: list[AacSegmentPlacement] = []
    video_s = 0.0
    packets_out = 0
    for segment in segments:
        track = tracks[segment.path]
        rate = track.timescale
        count = len(track.sizes)
        frame_s = 1024 / rate
        duration_s = segment.duration_s
        if duration_s is None:
            source_end_s = (track.dts[-1] + 1024 - track.media_time) / rate if count else 0.0
            duration_s = max(0.0, source_end_s - segment.start_s)
        audio_s = packets_out * frame_s
        wanted_source_s = segment.start_s + (audio_s - video_s)
        wanted = (wanted_source_s * rate + track.media_time - (track.dts[0] if count else 0)) / 1024
        filler = _round_half_up(-wanted) if count and _round_half_up(wanted) < 0 else 0
        if filler > _MAX_FILLER_PACKETS:
            filler = 0
        if filler:
            packets_out += filler
            audio_s = packets_out * frame_s
            wanted_source_s += filler * frame_s
            wanted += filler
        first = min(max(_round_half_up(wanted), 0), count)
        wanted_count = _round_half_up((video_s + duration_s - audio_s) / frame_s)
        packet_count = min(max(wanted_count, 0), count - first)
        clamped = first != _round_half_up(wanted) or packet_count != wanted_count
        first_source_s = (
            (track.dts[first] - track.media_time) / rate if first < count else math.inf
        )
        placements.append(AacSegmentPlacement(
            path=segment.path,
            source_in_s=segment.start_s,
            video_start_s=video_s,
            video_end_s=video_s + duration_s,
            first_packet=first,
            packet_count=packet_count,
            first_packet_source_s=first_source_s,
            audio_start_s=audio_s,
            audio_end_s=audio_s + packet_count * frame_s,
            sync_s=first_source_s - wanted_source_s,
            clamped=clamped,
            filler_packets=filler,
        ))
        parts.append((track, range(first, first + packet_count)))
        packets_out += packet_count
        video_s += duration_s
    return parts, placements


def plan_aac_feed(segments: Sequence[AudioSegment]) -> AacFeedPlan:
    """Resolve segments to AAC sample ranges, refusing anything not losslessly joinable."""
    tracks: dict[str, Optional[AacTrack]] = {}
    for segment in segments:
        if not math.isfinite(segment.start_s) or segment.start_s < 0 or (
            segment.duration_s is not None and (
                not math.isfinite(segment.duration_s) or segment.duration_s <= 0
            )
        ):
            raise LiveMuxConfigError("Invalid source audio range")
        if segment.path not in tracks:
            tracks[segment.path] = open_aac_track(segment.path)
    present = [path for path, track in tracks.items() if track is not None]
    if not present:
        return AacFeedPlan(parts=[])
    missing = [path for path, track in tracks.items() if track is None]
    if missing:
        raise LiveMuxConfigError(
            "some clips have no audio track, so their audio cannot be joined "
            f"without re-encoding: {', '.join(missing)}"
        )
    formats = {tracks[path].stream_format for path in present}
    if len(formats) > 1:
        raise LiveMuxConfigError(
            f"clips use different AAC formats {sorted(formats)}; "
            "they cannot be joined without re-encoding"
        )
    parts, placements = _place_segments(segments, tracks)  # type: ignore[arg-type]
    plan = AacFeedPlan(parts=parts, placements=placements)
    for index, item in enumerate(placements, 1):
        frame_s = 1024 / tracks[item.path].timescale  # type: ignore[union-attr]
        # Whole packets keep each segment within half a frame; more than one
        # frame means the source has no audio where this segment needs it.
        if item.packet_count == 0 or abs(item.sync_s) > frame_s + 1e-9:
            raise LiveMuxConfigError(
                f"Segment {index} ({Path(item.path).name}): original AAC packets would be "
                f"{item.sync_s * 1000:+.1f} ms out of sync with the video "
                f"(limit one AAC frame, {frame_s * 1000:.1f} ms; "
                f"{item.packet_count} packets available from source packet {item.first_packet}). "
                "The source audio does not cover this range; re-encoding is forbidden. "
                "Plan: " + " | ".join(plan.report_lines())
            )
    return plan


class AacPipeFeeder:
    """Streams an ``AacFeedPlan`` into a pipe that FFmpeg reads as ``-f aac``.

    On Windows a named pipe server is created; FFmpeg opens it as a file and
    the writer thread blocks whenever FFmpeg is not ready for more audio, so
    audio is read at the pace of the video.  Elsewhere a FIFO is used.
    """

    def __init__(self, plan: AacFeedPlan, pipe_name: str) -> None:
        self.plan = plan
        self.pipe_name = pipe_name
        self.error: Optional[BaseException] = None
        self.bytes_written = 0
        self.completed = False
        self._handle = None
        self._closed = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if os.name == "nt":
            import ctypes

            from ctypes import wintypes
            # Private prototypes: do not mutate the exporter's shared kernel32.
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            signatures = {
                "CreateNamedPipeW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p], wintypes.HANDLE),
                "ConnectNamedPipe": ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
                "WriteFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL),
                "FlushFileBuffers": ([wintypes.HANDLE], wintypes.BOOL),
                "DisconnectNamedPipe": ([wintypes.HANDLE], wintypes.BOOL),
                "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
                "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
                "CancelSynchronousIo": ([wintypes.HANDLE], wintypes.BOOL),
            }
            for name, (args, result) in signatures.items():
                function = getattr(self._kernel32, name)
                function.argtypes, function.restype = args, result
            handle = self._kernel32.CreateNamedPipeW(
                pipe_name,
                0x00000002,  # PIPE_ACCESS_OUTBOUND
                0x00000000,  # PIPE_TYPE_BYTE | PIPE_WAIT
                1,
                1024 * 1024,
                1024 * 1024,
                0,
                None,
            )
            if handle in (None, 0, ctypes.c_void_p(-1).value):
                raise LiveMuxConfigError(
                    f"cannot create audio pipe {pipe_name} (error {ctypes.get_last_error()})"
                )
            self._handle = handle
        else:
            os.mkfifo(pipe_name)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="AacPipeFeeder", daemon=True)
        self._thread.start()

    def _write_all(self, data: bytes) -> bool:
        if os.name != "nt":
            self._fifo.write(data)
            return True
        import ctypes

        view = memoryview(data)
        while view:
            if self._closed.is_set():
                return False
            written = ctypes.c_ulong(0)
            ok = self._kernel32.WriteFile(
                ctypes.c_void_p(self._handle), bytes(view[:65536]), min(len(view), 65536),
                ctypes.byref(written), None,
            )
            if not ok:
                if self._closed.is_set():
                    return False
                raise LiveMuxConfigError(f"AAC pipe write failed (error {ctypes.get_last_error()}); packets incomplete")
            if written.value == 0:
                raise LiveMuxConfigError("AAC pipe write made no progress")
            view = view[written.value:]
        return True

    def _run(self) -> None:
        try:
            if self._closed.is_set():
                return
            if os.name == "nt":
                import ctypes

                connected = self._kernel32.ConnectNamedPipe(ctypes.c_void_p(self._handle), None)
                if not connected and ctypes.get_last_error() != 535:  # ERROR_PIPE_CONNECTED
                    if not self._closed.is_set():
                        raise LiveMuxConfigError(
                            f"FFmpeg did not open audio pipe (error {ctypes.get_last_error()})"
                        )
                    return
            else:
                self._fifo = open(self.pipe_name, "wb")
            for frames in self.plan.frames():
                if self._closed.is_set():
                    return
                try:
                    if not self._write_all(frames):
                        return
                except BrokenPipeError:
                    return
                self.bytes_written += len(frames)
            self.completed = True
        except BaseException as exc:  # surfaced to the exporter through .error
            if not self._closed.is_set():
                self.error = exc
        finally:
            self._close_writer()

    def _close_writer(self) -> None:
        if os.name == "nt":
            if self._handle is not None:
                import ctypes

                # Normal EOF must drain buffered packets; abort must not wait
                # for a reader that has stopped consuming them.
                if self.completed and not self._closed.is_set():
                    self._kernel32.FlushFileBuffers(ctypes.c_void_p(self._handle))
                self._kernel32.DisconnectNamedPipe(ctypes.c_void_p(self._handle))
                self._kernel32.CloseHandle(ctypes.c_void_p(self._handle))
                self._handle = None
        else:
            fifo = getattr(self, "_fifo", None)
            if fifo is not None:
                try:
                    fifo.close()
                except OSError:
                    pass
                self._fifo = None

    def close(self, timeout: float = 5.0) -> None:
        """Stop feeding (cancel/abort) and release the pipe.

        A writer blocked in WriteFile is released when FFmpeg exits or is
        killed; one still waiting for FFmpeg to open the pipe is released by
        connecting to the pipe ourselves.
        """
        self._closed.set()
        if os.name == "nt" and self._thread is not None and self._thread.is_alive():
            import ctypes
            deadline = time.monotonic() + timeout
            while self._thread.is_alive() and time.monotonic() < deadline:
                thread_handle = self._kernel32.OpenThread(0x0001, False, self._thread.native_id)
                if thread_handle:
                    try:
                        self._kernel32.CancelSynchronousIo(thread_handle)
                    finally:
                        self._kernel32.CloseHandle(thread_handle)
                self._thread.join(min(0.05, max(0.0, deadline - time.monotonic())))
        if self._thread is not None:
            self._thread.join(0 if os.name == "nt" else timeout)
            if self._thread.is_alive():
                raise LiveMuxConfigError("AAC pipe worker did not stop after cancellation")
        if self._thread is None or not self._thread.is_alive():
            self._close_writer()
        if os.name != "nt":
            try:
                os.unlink(self.pipe_name)
            except OSError:
                pass

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
