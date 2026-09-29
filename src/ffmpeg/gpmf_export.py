"""Safe stream-copy attachment of original GoPro GPMF MP4 metadata."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
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
