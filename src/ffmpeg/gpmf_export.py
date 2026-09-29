"""Safe stream-copy attachment of original GoPro GPMF MP4 metadata."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GPMF_MISSING_MESSAGE = "GPMF: brak strumienia w pliku źródłowym"


def detect_gpmf_stream(ffprobe_exe: str, source_path: str | Path) -> dict[str, Any] | None:
    """Return the actual gpmd stream description, never assuming a stream index."""
    result = subprocess.run(
        [ffprobe_exe, "-v", "error", "-show_streams", "-of", "json", str(source_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout or "{}")
    for stream in data.get("streams", []):
        tags = stream.get("tags") or {}
        codec_tag = str(stream.get("codec_tag_string") or "").lower()
        handler = str(tags.get("handler_name") or "").lower()
        codec_name = str(stream.get("codec_name") or "").lower()
        is_gpmf = codec_tag == "gpmd" or (
            stream.get("codec_type") == "data"
            and ("gopro met" in handler or "gopro metadata" in handler)
            and codec_name in {"bin_data", "unknown"}
        )
        if is_gpmf:
            return stream
    return None


def _probe_gpmf(ffprobe_exe: str, output_path: Path) -> dict[str, Any] | None:
    return detect_gpmf_stream(ffprobe_exe, output_path)


def _probe_duration(ffprobe_exe: str, path: Path) -> float:
    result = subprocess.run(
        [ffprobe_exe, "-v", "error", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(result.stdout or "{}").get("format", {}).get("duration") or 0.0)


@dataclass
class InlineGpmfPlan:
    """The one GPMF input shared by all final mux implementations."""

    status: str
    input_path: Path | None = None
    stream_index: int | None = None
    temporary_dir: Path | None = None

    @property
    def enabled(self) -> bool:
        return self.input_path is not None and self.stream_index is not None

    def cleanup(self) -> None:
        if self.temporary_dir is None or not self.temporary_dir.is_dir():
            return
        for path in self.temporary_dir.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)
        self.temporary_dir.rmdir()
        self.temporary_dir = None


def inline_gpmf_mux_args(plan: InlineGpmfPlan | None, input_index: int) -> tuple[list[str], list[str]]:
    """Return an input and its exact gpmd mapping for an existing final mux."""
    if plan is None or not plan.enabled:
        return [], []
    return ["-i", str(plan.input_path)], [
        "-map", f"{input_index}:{plan.stream_index}",
        "-c:d", "copy", "-copy_unknown", "-tag:d:0", "gpmd",
    ]


def _run_metadata_copy(command: list[str], cancel_event: Any = None) -> None:
    """Supervise a small data-only preparation; never touch rendered video."""
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    started = time.monotonic()
    last_log = started
    try:
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                process.wait()
                raise RuntimeError("GPMF metadata preparation cancelled")
            now = time.monotonic()
            if now - last_log >= 5.0:
                print(
                    f"[GPMF PREP WATCHDOG] pid={process.pid} elapsed_s={now-started:.1f} "
                    f"alive=YES action=observe",
                    flush=True,
                )
                last_log = now
            time.sleep(0.1)
        stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
        if process.returncode != 0:
            raise RuntimeError(f"GPMF metadata preparation failed ({process.returncode}): {stderr[-2000:]}")
    finally:
        if process.stderr:
            process.stderr.close()


def prepare_inline_gpmf(
    *,
    ffmpeg_exe: str,
    ffprobe_exe: str,
    source_paths: list[str | Path],
    output_path: str | Path,
    video_timeline: Any = None,
    duration_s: float = 0.0,
    cut_regions: list[tuple[float, float]] | None = None,
    max_frames: int | None = None,
    target_fps: float = 30.0,
    start_frame: int = 0,
    cancel_event: Any = None,
) -> InlineGpmfPlan:
    """Select gpmd before rendering; prepare only metadata for trims/concat.

    Full single-file exports use the original source directly.  Every other
    retained segment is copied into a tiny data-only MP4.  The concat demuxer
    then shifts segments by their video timeline durations before the one final
    video/audio/GPMF mux starts.
    """
    clips = list(getattr(video_timeline, "clips", ()) or ())
    if clips:
        segments = [
            (Path(clip.path), float(clip.local_start_s), float(clip.duration_s),
             float(getattr(clip, "source_duration_s", 0.0) or 0.0))
            for clip in clips
        ]
    elif len(source_paths) == 1:
        source = Path(source_paths[0])
        source_duration = _probe_duration(ffprobe_exe, source)
        segments = [(source, 0.0, float(duration_s or source_duration), source_duration)]
    else:
        print("GPMF: niepełne dane w zestawie wieloplikowym (brak osi czasu)", flush=True)
        return InlineGpmfPlan("missing_timeline")

    if cut_regions and not clips and segments:
        source, _start, duration, source_duration = segments[0]
        retained = [(0.0, duration)]
        for cut_start, cut_end in sorted(cut_regions):
            retained = [
                piece
                for left, right in retained
                for piece in ((left, min(right, cut_start)), (max(left, cut_end), right))
                if piece[1] - piece[0] > 1e-6
            ]
        segments = [(source, left, right-left, source_duration) for left, right in retained]

    if start_frame > 0 and target_fps > 0:
        skip_s = start_frame / target_fps
        shifted = []
        for source, start, duration, source_duration in segments:
            if skip_s >= duration:
                skip_s -= duration
                continue
            shifted.append((source, start + skip_s, duration - skip_s, source_duration))
            skip_s = 0.0
        segments = shifted
    if max_frames is not None and max_frames > 0 and target_fps > 0:
        remaining_s = max_frames / target_fps
        limited = []
        for source, start, duration, source_duration in segments:
            keep_s = min(duration, remaining_s)
            if keep_s <= 0:
                break
            limited.append((source, start, keep_s, source_duration))
            remaining_s -= keep_s
        segments = limited

    if not segments or any(segment[2] <= 0 for segment in segments):
        return InlineGpmfPlan("empty_timeline")

    streams: dict[Path, dict[str, Any] | None] = {}
    for source, _start, _duration, _source_duration in segments:
        if source not in streams:
            streams[source] = detect_gpmf_stream(ffprobe_exe, source)
    if any(stream is None for stream in streams.values()):
        if len(segments) > 1:
            print("GPMF: niepełne dane w zestawie wieloplikowym", flush=True)
            return InlineGpmfPlan("partial_multifile_missing")
        print(GPMF_MISSING_MESSAGE, flush=True)
        return InlineGpmfPlan("source_missing")

    if len(segments) == 1:
        source, start, duration, source_duration = segments[0]
        source_duration = source_duration or _probe_duration(ffprobe_exe, source)
        if start <= 1e-6 and abs(source_duration - duration) <= 0.1:
            index = int(streams[source]["index"])
            print(f"GPMF_SOURCE_STREAM_INDEX={index} GPMF_MUX_MODE=inline_source", flush=True)
            return InlineGpmfPlan("ready_full", source, index)

    temp_dir = Path(tempfile.mkdtemp(prefix="telem_gpmd_"))
    plan = InlineGpmfPlan("preparing", temporary_dir=temp_dir)
    try:
        entries: list[str] = []
        for ordinal, (source, start, duration, _source_duration) in enumerate(segments):
            index = int(streams[source]["index"])
            segment_path = temp_dir / f"segment_{ordinal:04d}.mp4"
            _run_metadata_copy([
                ffmpeg_exe, "-hide_banner", "-nostdin", "-v", "error", "-y",
                "-ss", f"{start:.9f}", "-i", str(source),
                "-ss", "0", "-t", f"{duration:.9f}",
                "-map", f"0:{index}", "-c:d", "copy", "-copy_unknown",
                "-tag:d:0", "gpmd", str(segment_path),
            ], cancel_event)
            if detect_gpmf_stream(ffprobe_exe, segment_path) is None:
                raise RuntimeError(f"GPMF segment contains no gpmd: {source} [{start}, {start+duration}]")
            escaped = str(segment_path).replace("\\", "/").replace("'", "'\\''")
            entries.extend([f"file '{escaped}'\n", f"duration {duration:.9f}\n"])
        concat_path = temp_dir / "segments.ffconcat"
        concat_path.write_text("ffconcat version 1.0\n" + "".join(entries), encoding="utf-8")
        combined_path = temp_dir / "gpmd_timeline.mp4"
        _run_metadata_copy([
            ffmpeg_exe, "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-map", "0:0", "-c:d", "copy", "-copy_unknown",
            "-tag:d:0", "gpmd", str(combined_path),
        ], cancel_event)
        stream = detect_gpmf_stream(ffprobe_exe, combined_path)
        if stream is None:
            raise RuntimeError("GPMF metadata timeline has no gpmd stream")
        plan.status = "ready_metadata_timeline"
        plan.input_path = combined_path
        plan.stream_index = int(stream["index"])
        print(
            f"GPMF_MUX_MODE=inline_metadata GPMF_SOURCE_SEGMENTS={len(segments)} "
            f"GPMF_METADATA_BYTES={combined_path.stat().st_size}",
            flush=True,
        )
        return plan
    except BaseException:
        plan.cleanup()
        raise


def attach_original_gpmf(
    *,
    ffmpeg_exe: str,
    ffprobe_exe: str,
    source_paths: list[str | Path],
    output_path: str | Path,
    trimmed: bool = False,
    cancel_event: Any = None,
    active_process_holder: dict[str, Any] | None = None,
    progress_cb: Any = None,
) -> dict[str, Any]:
    """Copy a single source gpmd track into an already rendered MP4.

    Trimmed and multi-file exports are explicitly unsupported until the app can
    compute a correct GPMF time window/concatenated metadata timeline.
    """
    output = Path(output_path)
    if len(source_paths) != 1:
        reason = "unsupported_multifile" if len(source_paths) > 1 else "missing_source"
        print(f"GPMF: preservation {reason}; output left unchanged", flush=True)
        return {"gpmf_status": reason, "gpmf_attached": False, "gpmf_attach_seconds": 0.0}
    if trimmed:
        print("GPMF: preservation unsupported for trimmed export; output left unchanged", flush=True)
        return {"gpmf_status": "unsupported_trimmed", "gpmf_attached": False, "gpmf_attach_seconds": 0.0}

    source = Path(source_paths[0])
    source_stream = detect_gpmf_stream(ffprobe_exe, source)
    if source_stream is None:
        print(GPMF_MISSING_MESSAGE, flush=True)
        return {
            "gpmf_status": "source_missing",
            "gpmf_attached": False,
            "gpmf_source_detected": False,
            "gpmf_source_stream_index": None,
            "gpmf_attach_seconds": 0.0,
        }

    stream_index = int(source_stream["index"])
    print(
        f"GPMF_SOURCE_DETECTED=YES GPMF_SOURCE_STREAM_INDEX={stream_index} "
        f"codec_tag={source_stream.get('codec_tag_string', '')}",
        flush=True,
    )
    source_duration = _probe_duration(ffprobe_exe, source)
    render_duration = _probe_duration(ffprobe_exe, output)
    # A duration mismatch means this is effectively a trim or partial render;
    # refusing it is safer than attaching the full source timeline.
    if source_duration <= 0 or render_duration <= 0 or abs(source_duration - render_duration) > 0.1:
        print(
            "GPMF: source/render durations do not match; metadata attachment skipped",
            flush=True,
        )
        return {
            "gpmf_status": "duration_mismatch",
            "gpmf_attached": False,
            "gpmf_source_detected": True,
            "gpmf_source_stream_index": stream_index,
            "gpmf_source_duration": source_duration,
            "gpmf_render_duration": render_duration,
            "gpmf_attach_seconds": 0.0,
        }
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{output.stem}.gpmf-", suffix=output.suffix or ".mp4", dir=str(output.parent),
    )
    os.close(fd)
    temp_output = Path(tmp_name)
    temp_output.unlink(missing_ok=True)
    command = [
        ffmpeg_exe, "-hide_banner", "-nostats", "-y",
        "-i", str(output), "-i", str(source),
        "-map", "0:v?", "-map", "0:a?", "-map", f"1:{stream_index}",
        "-c", "copy", "-copy_unknown", "-tag:d:0", "gpmd",
        "-map_metadata", "0", "-map_chapters", "0",
        str(temp_output),
    ]
    started = time.perf_counter()
    last_progress_at = 0.0
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if active_process_holder is not None:
            active_process_holder["process"] = process
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise RuntimeError("GPMF attachment cancelled")
            now = time.perf_counter()
            if progress_cb is not None and now - last_progress_at >= 1.0:
                try:
                    file_size = temp_output.stat().st_size if temp_output.exists() else 0
                    base_size = output.stat().st_size if output.exists() else file_size
                    ratio = min(1.0, file_size / max(1, base_size))
                    progress_cb(
                        0, 0, now - started, 0.0,
                        {
                            "phase": "finalize",
                            "finalize_stage": "Finalizacja: dołączanie oryginalnego GPMF",
                            "global_pct": min(99.8, 98.0 + 1.8 * ratio),
                            "file_size_bytes": file_size,
                        },
                    )
                except Exception:
                    pass
                last_progress_at = now
            time.sleep(0.1)
        stderr = process.stderr.read() if process.stderr is not None else ""
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg GPMF stream-copy attach failed: {stderr[-4000:]}")
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("GPMF attachment cancelled")

        output_stream = _probe_gpmf(ffprobe_exe, temp_output)
        if output_stream is None:
            raise RuntimeError("FFmpeg output validation failed: gpmd track missing")
        os.replace(temp_output, output)
        elapsed = time.perf_counter() - started
        print(
            f"GPMF_OUTPUT_DETECTED=YES GPMF_OUTPUT_STREAM_INDEX={output_stream.get('index')} "
            f"codec_tag={output_stream.get('codec_tag_string', '')} attach_seconds={elapsed:.3f}",
            flush=True,
        )
        return {
            "gpmf_status": "attached",
            "gpmf_attached": True,
            "gpmf_source_detected": True,
            "gpmf_source_stream_index": stream_index,
            "gpmf_output_stream_index": int(output_stream["index"]),
            "gpmf_source_codec_tag": source_stream.get("codec_tag_string"),
            "gpmf_output_codec_tag": output_stream.get("codec_tag_string"),
            "gpmf_source_duration": source_duration,
            "gpmf_output_duration": _probe_duration(ffprobe_exe, output),
            "gpmf_attach_seconds": elapsed,
            "video_stream_copy_during_gpmf_attach": True,
            "audio_behavior_unchanged": True,
        }
    finally:
        if process is not None and process.stderr is not None:
            process.stderr.close()
        if process is not None and active_process_holder is not None:
            if active_process_holder.get("process") is process:
                active_process_holder.pop("process", None)
        temp_output.unlink(missing_ok=True)
