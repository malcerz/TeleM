"""FFmpeg piping and streaming logic.

Manages writing frames into the FFmpeg stdin pipe asynchronously using writer threads,
handles process lifetime, and reports progress.
"""

from __future__ import annotations

import math
import os
import queue
import copy
import json
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from src.ffmpeg.detection import detect_gpu_decoder
from src.ffmpeg.intel_backend import intel_device_selection, intel_ffmpeg_device_args, resolve_intel_force
from src.ffmpeg.worker_cache import init_worker
from src.ffmpeg.command_builder import (
    _build_stream_ffmpeg_cmd,
    build_text_bbox_context,
    get_layout_hud_bbox,
    get_layout_hud_regions,
    is_nv_rot180_cuda,
)
from src.ffmpeg.shared_memory import (
    SharedFramePool,
    _init_worker_with_shm,
    render_frame_shm_job,
)
from src.ffmpeg.frame_renderer import render_frame_bytes_job
from src.benchmark import BenchmarkTracker
from src.ffmpeg.pipeline_audit import PipelineAuditRecorder, env_enabled
from src.multifile import timeline_absolute_end


# ETAP 5B.6: the production layout with valid FIT battery/solar fields needs
# five natural HUD clusters to stay below the existing 70% atlas fallback.
# Keep the previous four-region geometry available through benchmark/audit
# overrides; the transport threshold itself remains unchanged.
NVIDIA_HUD_MAX_REGIONS = 5
NVIDIA_HUD_GRID_PX = 16


def _probe_intel_native_source(input_file: str, ffmpeg_exe: str) -> tuple[bool, str]:
    """Allow the native slice only for single-file 8-bit SDR input."""
    ffprobe = str(Path(ffmpeg_exe).with_name("ffprobe.exe"))
    if not Path(ffprobe).exists():
        ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt,color_space,color_transfer,color_primaries",
             "-of", "default=nw=1", input_file],
            capture_output=True, text=True, timeout=8,
        )
        if result.returncode != 0:
            return False, "source_probe_failed"
        info = result.stdout.lower()
        if "10le" in info or "10be" in info or "12le" in info or "12be" in info:
            return False, "hdr_or_non_8bit_source"
        if any(token in info for token in ("bt2020", "arib-std-b67", "smpte2084", "hlg")):
            return False, "hdr_or_non_sdr_source"
        return True, "sdr_8bit_source"
    except Exception:
        return False, "source_probe_failed"


def _probe_intel_cpu_download_format(input_file: str, ffmpeg_exe: str) -> str:
    """Select a CPU-compatible download format without narrowing HDR to 8-bit."""
    ffprobe = str(Path(ffmpeg_exe).with_name("ffprobe.exe"))
    if not Path(ffprobe).exists():
        ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt", "-of", "default=nw=1", input_file],
            capture_output=True, text=True, timeout=8,
        )
        pix_fmt = result.stdout.lower()
        if any(token in pix_fmt for token in ("10le", "10be", "12le", "12be", "p010", "p016")):
            return "p010le"
    except Exception:
        pass
    return "nv12"


def _flag_on_env(name: str) -> bool:
    """ASCII-safe env flag: default ON, accepts 0/false/off as OFF."""
    return os.environ.get(name, "1").strip().lower() not in ("0", "false", "off")


def resolve_intel_qsv_bitrate(video_bitrate: str):
    """ETAP 4K: single source of truth for the Intel QSV target bitrate.

    Returns (effective_bitrate, rc_source):
      - rc_source="application"  -> GUI/CLI video_bitrate unchanged
      - rc_source="env_override" -> TELEM_INTEL_QSV_BITRATE_MBPS wins
        (Intel-only diagnostic/experimental override; invalid values are
        ignored and fall back to the application bitrate).
    """
    raw = os.environ.get("TELEM_INTEL_QSV_BITRATE_MBPS", "").strip()
    if raw:
        try:
            float(raw)
            return f"{raw}M", "env_override"
        except ValueError:
            pass
    return video_bitrate, "application"


def _intel_hud_region_decision(
    layout: dict,
    canvas_w: int,
    canvas_h: int,
) -> tuple[int, int, int, int, float, str]:
    """ETAP 4B: bounded-HUD transport decision for the Intel paths.

    Returns ``(hud_x, hud_y, stream_w, stream_h, bbox_ratio, mode)``
    where ``mode`` is ``"region"``, ``"full_threshold"`` or ``"full_geometry"``.

    The default threshold 0.85 was confirmed by the ETAP 4B break-even
    benchmark (scratch/intel_etap4bc/breakeven_*.json): REGION stays at or
    above FULL speed up to the measured maximum ratios on both 1080p and 4K,
    so the conservative geometric gate is kept. Override only for experiments:

        TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO=0.0..1.0
    """
    bx, by, bw, bh = get_layout_hud_bbox(layout, canvas_w, canvas_h)
    x1 = max(0, min(canvas_w, int(bx)))
    y1 = max(0, min(canvas_h, int(by)))
    x2 = max(x1, min(canvas_w, int(bx + bw)))
    y2 = max(y1, min(canvas_h, int(by + bh)))
    if x1 % 2:
        x1 = max(0, x1 - 1)
    if y1 % 2:
        y1 = max(0, y1 - 1)
    if (x2 - x1) % 2:
        x2 = min(canvas_w, x2 + 1)
    if (y2 - y1) % 2:
        y2 = min(canvas_h, y2 + 1)
    region_area = max(0, x2 - x1) * max(0, y2 - y1)
    full_area = canvas_w * canvas_h
    ratio = region_area / full_area if full_area else 1.0
    try:
        threshold = float(os.environ.get(
            "TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO", "0.85"))
    except ValueError:
        threshold = 0.85
    if region_area <= 0:
        return 0, 0, canvas_w, canvas_h, ratio, "full_geometry"
    if ratio >= threshold:
        return 0, 0, canvas_w, canvas_h, ratio, "full_threshold"
    return x1, y1, max(2, x2 - x1), max(2, y2 - y1), ratio, "region"


def _intel_hud_region_gate(
    intel_gpu_resident: bool,
    rotation_degrees: int,
    container_rotation: int,
    encoder: str = "",
) -> bool:
    """ETAP 3C/4A shared bounded-HUD gate for the Intel paths.

    - Native (GPU-resident): ETAP 3C switch ``TELEM_INTEL_HUD_REGION``
      (default ON), unchanged.
    - CPU_REFERENCE (ETAP 4A): own switch ``TELEM_INTEL_CPU_REF_HUD_REGION``
      (default ON).
      ETAP 5D: the Intel pipeline imports sources with autorotate ON (no
      ``-noautorotate``, no manual vflip/hflip), so the base video enters the
      filter graph already upright and the HUD canvas crop shares coordinates
      with the overlay destination for ANY source rotation.  The former
      rotation!=0 exclusion (which silently forced FULL_CANVAS for every
      rotated GoPro in real GUI runs) therefore no longer applies to Intel;
      other encoders keep the conservative unrotated-only rule.

    Called once per render -- no per-frame logging, ASCII-safe.
    """

    if intel_gpu_resident:
        return _flag_on_env("TELEM_INTEL_HUD_REGION")
    if encoder == "intel":
        return _flag_on_env("TELEM_INTEL_CPU_REF_HUD_REGION")
    return (
        rotation_degrees == 0
        and container_rotation == 0
        and _flag_on_env("TELEM_INTEL_CPU_REF_HUD_REGION")
    )


def _cancel_log(message: str, started: float | None = None, process: Any = None) -> None:
    """ASCII-safe, bounded-cancel diagnostics."""
    elapsed = (time.perf_counter() - started) if started is not None else 0.0
    thread = threading.current_thread().name
    pid = getattr(process, "pid", None) if process is not None else None
    pid_text = f" pid={pid}" if pid is not None else ""
    print(f"[RenderCancel] {message} elapsed={elapsed:.3f}s thread={thread}{pid_text}", flush=True)


class _RenderExecutor:
    """ProcessPoolExecutor context with non-blocking cancellation exit."""

    def __init__(self, *args: Any, cancel_event: Any = None, **kwargs: Any) -> None:
        from concurrent.futures import ProcessPoolExecutor
        self._args = args
        self._kwargs = kwargs
        self._cancel_event = cancel_event
        self.executor = ProcessPoolExecutor(*args, **kwargs)

    def __enter__(self):
        return self.executor

    def __exit__(self, exc_type, exc, tb):
        cancelled = self._cancel_event is not None and self._cancel_event.is_set()
        if cancelled:
            for child in list(getattr(self.executor, "_processes", {}).values()):
                try:
                    child.terminate()
                except Exception:
                    pass
            self.executor.shutdown(wait=False, cancel_futures=True)
        else:
            self.executor.shutdown(wait=True)
        return False


def _wait_process_bounded(process: Any, timeout: float) -> bool:
    """Wait without ever allowing process cleanup to become unbounded."""
    deadline = time.monotonic() + max(0.0, timeout)
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    return process.poll() is not None


def _stop_ffmpeg_process(
    process: Any, cancel_started: float | None = None,
    graceful_timeout: float = 10.0,
) -> int | None:
    """Graceful stdin close, then bounded terminate/kill process-tree fallback."""
    if process is None:
        return None
    if process.poll() is not None:
        setattr(process, "_telem_cancel_mode", "graceful")
        _cancel_log(f"ffmpeg exited rc={process.returncode}", cancel_started, process)
        return process.returncode

    _cancel_log("ffmpeg graceful stop requested", cancel_started, process)
    try:
        if process.stdin is not None:
            process.stdin.close()
    except Exception:
        pass
    _cancel_log("stdin_closed", cancel_started, process)
    _cancel_log("ffmpeg graceful wait start", cancel_started, process)
    graceful_deadline = time.monotonic() + max(0.1, graceful_timeout)
    next_progress = 1
    while process.poll() is None and time.monotonic() < graceful_deadline:
        elapsed = time.monotonic() - (graceful_deadline - graceful_timeout)
        if elapsed >= next_progress:
            _cancel_log(f"ffmpeg still running after {next_progress}s", cancel_started, process)
            next_progress += 1
        time.sleep(0.05)
    if process.poll() is not None:
        setattr(process, "_telem_cancel_mode", "graceful")
        _cancel_log(f"ffmpeg exited rc={process.returncode}", cancel_started, process)
        return process.returncode

    _cancel_log("graceful timeout reached", cancel_started, process)
    try:
        process.terminate()
    except Exception:
        pass
    _cancel_log("terminate", cancel_started, process)
    if _wait_process_bounded(process, 1.0):
        setattr(process, "_telem_cancel_mode", "terminate")
        _cancel_log(f"ffmpeg exited rc={process.returncode}", cancel_started, process)
        return process.returncode

    # Windows terminate() is not guaranteed to include descendants.  Use the
    # built-in process-tree command only for the final hard-cleanup fallback.
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
                timeout=2.0,
            )
        except Exception:
            pass
    else:
        try:
            process.kill()
        except Exception:
            pass
    _cancel_log("kill", cancel_started, process)
    _wait_process_bounded(process, 1.0)
    setattr(process, "_telem_cancel_mode", "kill")
    _cancel_log("cleanup done", cancel_started, process)
    return process.poll()


def _validate_partial_mp4(output_file: str | Path) -> bool:
    """Validate a gracefully closed partial MP4 using the local ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not Path(output_file).exists():
        return False
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "format=duration:stream=codec_type", "-of", "json", str(output_file)],
            capture_output=True, text=True, timeout=5.0, check=False,
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout or "{}")
        duration = float((data.get("format") or {}).get("duration") or 0.0)
        streams = data.get("streams") or []
        return duration > 0.0 and any(s.get("codec_type") == "video" for s in streams)
    except Exception:
        return False


def _log_ffmpeg_tail(stdout_lines: list[str], cancel_started: float | None) -> None:
    for line in stdout_lines[-8:]:
        safe = str(line).encode("ascii", "replace").decode("ascii").strip()
        if safe:
            _cancel_log(f"ffmpeg tail: {safe}", cancel_started)


def _snap_nvidia_hud_layout(layout: dict[str, Any], canvas_w: int, canvas_h: int, grid_px: int) -> dict[str, Any]:
    """Return a runtime-only NVIDIA layout with indicator anchors snapped to a safe grid."""
    snapped = copy.deepcopy(layout)
    for cfg in snapped.get("indicators", {}).values():
        if not cfg or not cfg.get("enabled", True):
            continue
        for axis, dimension in (("x", canvas_w), ("y", canvas_h)):
            value = cfg.get(axis)
            if not isinstance(value, (int, float)):
                continue
            is_percent = value <= 100.0
            logical_px = (value / 100.0) * dimension if is_percent else value
            snapped_px = round(logical_px / grid_px) * grid_px
            if abs(snapped_px - logical_px) > grid_px:
                continue
            snapped_px = max(0, min(dimension, snapped_px))
            cfg[axis] = (snapped_px / dimension) * 100.0 if is_percent else snapped_px
    return snapped


def _pipe_writer_thread(
    write_queue: queue.Queue,
    stdin_buffer: Any,
    done_event: threading.Event,
    shm_pool: SharedFramePool | None = None,
    writer_stats: dict[str, Any] | None = None,
    audit: PipelineAuditRecorder | None = None,
    writer_failed: threading.Event | None = None,
    discard_pending: threading.Event | None = None,
) -> None:
    """Background thread that drains frame bytes to FFmpeg stdin pipe.

    Receives bytes or (slot, memoryview) from write_queue and writes to stdin_buffer.
    Terminates on the None sentinel, when done_event is set and the queue is
    empty, or immediately (discarding queued frames) when discard_pending is set.
    """
    bt = BenchmarkTracker.get_instance()

    def _release_item(item: Any) -> None:
        if isinstance(item, tuple):
            try:
                item[1].release()
            except Exception:
                pass
            if shm_pool is not None:
                try:
                    shm_pool.release(item[0])
                except Exception:
                    pass

    if audit is None:
        # Production hot path: no audit timestamps, qsize sampling, histogram
        # updates, or diagnostic locks.  The writer receives the SHM memoryview
        # and performs one direct BufferedWriter.write per frame.
        #
        # EOF contract: done_event means "producer finished submitting", NOT
        # "drop whatever is still queued".  The writer must write every frame
        # already enqueued before exiting (sentinel None, or empty queue after
        # done_event).  Queued frames are discarded ONLY when an explicit
        # cancel/error requested it via discard_pending (ETAP 5B tail-loss fix).
        try:
            while True:
                if discard_pending is not None and discard_pending.is_set():
                    while True:
                        try:
                            _release_item(write_queue.get_nowait())
                        except queue.Empty:
                            break
                    break
                try:
                    item = write_queue.get(timeout=0.5)
                except queue.Empty:
                    if done_event.is_set():
                        break
                    continue
                if item is None:
                    break
                bt.start_timer("ffmpeg_write")
                try:
                    if isinstance(item, tuple):
                        slot, memview = item[:2]
                        try:
                            stdin_buffer.write(memview)
                        finally:
                            try:
                                memview.release()
                            except Exception:
                                pass
                            if shm_pool is not None:
                                shm_pool.release(slot)
                    else:
                        stdin_buffer.write(item)
                finally:
                    bt.stop_timer("ffmpeg_write")
                    if writer_stats is not None:
                        now = time.perf_counter()
                        if writer_stats["first_frame_time"] is None:
                            writer_stats["first_frame_time"] = now
                        writer_stats["last_frame_time"] = now
                        writer_stats["frames_written"] += 1
        except (BrokenPipeError, OSError):
            if writer_failed is not None:
                writer_failed.set()
            pass
        return

    if writer_stats is not None:
        writer_stats["stream_type"] = type(stdin_buffer).__name__
        writer_stats["stream_module"] = type(stdin_buffer).__module__
        writer_stats["thread_started_ns"] = time.perf_counter_ns()

    try:
        while True:
            if discard_pending is not None and discard_pending.is_set():
                while True:
                    try:
                        _release_item(write_queue.get_nowait())
                    except queue.Empty:
                        break
                break
            get_started_ns = time.perf_counter_ns()
            queue_was_empty = write_queue.empty()
            try:
                item = write_queue.get(timeout=0.5)
            except queue.Empty:
                get_finished_ns = time.perf_counter_ns()
                if writer_stats is not None and queue_was_empty:
                    writer_stats["idle_wait_ns"] = writer_stats.get("idle_wait_ns", 0) + get_finished_ns - get_started_ns
                if done_event.is_set():
                    break
                continue
            get_finished_ns = time.perf_counter_ns()
            if writer_stats is not None and queue_was_empty:
                writer_stats["idle_wait_ns"] = writer_stats.get("idle_wait_ns", 0) + get_finished_ns - get_started_ns
            if item is None:  # sentinel
                break
            queue_depth = write_queue.qsize()
            bt.start_timer("ffmpeg_write")
            write_started_ns = time.perf_counter_ns()
            write_finished_ns: int | None = None
            try:
                if isinstance(item, tuple):
                    slot, memview = item[:2]
                    frame_index = item[2] if len(item) >= 3 else None
                    if audit is not None and frame_index is not None:
                        audit.mark(frame_index, "writer_dequeued_ns", get_finished_ns)
                        audit.mark(frame_index, "writer_queue_depth_after_get", queue_depth)
                        audit.mark(frame_index, "ffmpeg_write_started_ns", write_started_ns)
                    try:
                        requested_bytes = len(memview)
                        returned = stdin_buffer.write(memview)
                        returned_bytes = int(returned) if returned is not None else 0
                        if audit is not None and frame_index is not None:
                            audit.mark(frame_index, "writer_requested_bytes", requested_bytes)
                            audit.mark(frame_index, "writer_returned_bytes", returned_bytes)
                            audit.mark(frame_index, "writer_write_calls", 1)
                            if returned_bytes != requested_bytes:
                                audit.increment("partial_write_observed")
                        if writer_stats is not None:
                            writer_stats["requested_bytes"] = writer_stats.get("requested_bytes", 0) + requested_bytes
                            writer_stats["returned_bytes"] = writer_stats.get("returned_bytes", 0) + returned_bytes
                            writer_stats["write_calls"] = writer_stats.get("write_calls", 0) + 1
                            if returned_bytes != requested_bytes:
                                writer_stats["partial_write_frames"] = writer_stats.get("partial_write_frames", 0) + 1
                        write_finished_ns = time.perf_counter_ns()
                        if audit is not None and frame_index is not None:
                            audit.mark(frame_index, "ffmpeg_write_finished_ns", write_finished_ns)
                    finally:
                        try:
                            memview.release()
                        except Exception:
                            pass
                        if shm_pool is not None:
                            shm_pool.release(slot)
                        if audit is not None and frame_index is not None:
                            audit.mark(frame_index, "shm_released_ns", time.perf_counter_ns())
                else:
                    frame_index = None
                    if audit is not None:
                        audit.increment("raw_bytes_writer_items")
                    stdin_buffer.write(item)
            finally:
                if write_finished_ns is None:
                    write_finished_ns = time.perf_counter_ns()
                if writer_stats is not None:
                    writer_stats["busy_write_ns"] = writer_stats.get("busy_write_ns", 0) + max(0, write_finished_ns - write_started_ns)
                if audit is not None and frame_index is not None and audit.frame(frame_index).get("ffmpeg_write_finished_ns") is None:
                    audit.mark(frame_index, "ffmpeg_write_finished_ns", write_finished_ns)
                bt.stop_timer("ffmpeg_write")
                now = time.perf_counter()
                if writer_stats is not None:
                    if writer_stats["first_frame_time"] is None:
                        writer_stats["first_frame_time"] = now
                    writer_stats["last_frame_time"] = now
                    writer_stats["frames_written"] += 1
    except (BrokenPipeError, OSError):
        if writer_failed is not None:
            writer_failed.set()
        pass
    finally:
        if writer_stats is not None:
            writer_stats["thread_finished_ns"] = time.perf_counter_ns()


def _report_stream_progress(
    done: int, total: int, start_time: float, progress_cb: Optional[Callable],
    on_render_progress: Optional[Callable] = None,
    target_fps: Optional[float] = None,
    audit: PipelineAuditRecorder | None = None,
) -> None:
    """Report streaming progress and the latest export timestamp for preview."""
    elapsed = time.time() - start_time
    m, s = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    fps = done / elapsed if elapsed > 0 else 0
    stats = f"Stream: {done}/{total} | fps: {fps:.1f} | elapse: {h:02d}:{m:02d}:{s:02d}"
    if progress_cb:
        callback_started = time.perf_counter_ns() if audit is not None else 0
        progress_cb(done, stats)
        if audit is not None:
            audit.add_stat("progress_callback", (time.perf_counter_ns() - callback_started) / 1_000_000.0)
    if on_render_progress:
        hud_state = None
        if target_fps and target_fps > 0 and done > 0:
            frame = min(max(0, total - 1), done - 1)
            hud_state = {"frame": frame, "ts": frame / target_fps}
        callback_started = time.perf_counter_ns() if audit is not None else 0
        on_render_progress(done, total, elapsed, fps, hud_state)
        if audit is not None:
            audit.add_stat("preview_progress_callback", (time.perf_counter_ns() - callback_started) / 1_000_000.0)


def _report_phase(
    on_render_progress: Optional[Callable],
    phase: str,
    pct: float,
    label: str,
    elapsed: float = 0.0,
) -> None:
    """Report a phase-level progress milestone on the shared render-progress
    contract so the GUI can map the WHOLE export onto one continuous 0..100 bar.

    Regular frame-level reports keep the existing
    ``(completed, total, elapsed, fps, {"frame", "ts"})`` shape; phase reports
    are distinguished by the ``"phase"`` key and carry a phase-local ``pct`` in
    0..1 plus a status ``label``:

    - ``"prep"``     -> HUD preparation (GUI maps to the 0..10% slice)
    - ``"finalize"`` -> final mux / drain (GUI maps to the 98..100% slice)

    This is a progress-reporting-only change: it never alters rendering logic.
    """
    if on_render_progress is None:
        return
    on_render_progress(
        0, 0, max(0.0, elapsed), 0.0,
        {"phase": phase, "pct": max(0.0, min(1.0, pct)), "label": label},
    )


def _acquire_shm_slot(
    shm_pool: "SharedFramePool",
    process: Any,
    stdout_lines: list[str],
    timeout: float = 30.0,
    cancel_event: Any = None,
) -> int:
    """Acquire an SHM slot, failing fast if FFmpeg has already exited.

    If FFmpeg dies (e.g. filter graph error), nothing drains the pipe, so SHM
    slots would never be released and ``acquire`` would block for the full
    timeout before raising ``queue.Empty``. Surface the FFmpeg log instead.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise queue.Empty("render cancellation requested")
        if process.poll() is not None:
            raise RuntimeError(
                f"FFmpeg process died unexpectedly (exit code {process.returncode}). "
                f"FFmpeg log output:\n" + "\n".join(stdout_lines[-30:])
            )
        try:
            return shm_pool.acquire(timeout=0.1)
        except queue.Empty:
            continue
    if process.poll() is not None:
        raise RuntimeError(
            f"FFmpeg process died unexpectedly (exit code {process.returncode}). "
            f"FFmpeg log output:\n" + "\n".join(stdout_lines[-30:])
        )
    raise queue.Empty("Timed out waiting for free SHM slot")


def run_ffmpeg_with_progress(
    cmd: list[str],
    total_frames: int,
    progress_cb: Callable,
    msg_prefix: str,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
) -> None:
    """Run ffmpeg and parse progress output."""
    cmd.extend(["-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, startupinfo=startupinfo,
    )
    if active_process_holder is not None:
        active_process_holder["process"] = process

    frame, fps, out_time, speed = 0, "0", "00:00:00", "0x"
    start_time = time.time()
    other_output: list[str] = []

    for line in process.stdout:
        if cancel_event is not None and cancel_event.is_set():
            _stop_ffmpeg_process(process)
            break
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if "=" not in line:
            other_output.append(line.strip())
            continue
        if key == "frame":
            try:
                frame = min(int(val), total_frames)
            except Exception:
                pass
        elif key == "fps":
            fps = val
        elif key == "out_time":
            out_time = val.split(".")[0]
        elif key == "speed":
            speed = val
        elif key == "progress":
            elapsed = int(time.time() - start_time)
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            stats = (
                f"{msg_prefix}: {frame}/{total_frames} | fps: {fps} | "
                f"speed: {speed} | time: {out_time} | elapse: {h:02d}:{m:02d}:{s:02d}"
            )
            if progress_cb:
                progress_cb(frame, stats)
    if process.poll() is None:
        _stop_ffmpeg_process(process)
    rc = process.returncode
    if rc != 0:
        extra = "\n".join(other_output).strip()
        raise RuntimeError(f"FFmpeg process failed with exit code {rc}\n{extra}")
    if active_process_holder is not None:
        active_process_holder["process"] = None


def resolve_hud_resolution_policy(
    encoder: str,
    render_w: int,
    render_h: int,
    user_option: Any = "Auto",
) -> tuple[float, str]:
    """Resolve the effective HUD resolution scale and generate a diagnostic message.

    Policy:
    - Manual 100% (1.0) -> 1.0
    - Manual 75% (0.75) -> 0.75
    - Manual 50% (0.5) -> 0.5
    - Auto (or default):
      - If encoder == "intel" and (render_w, render_h) == (3840, 2160):
        -> 0.75 (2560x1440 scaled HUD, validated in ETAP 6B with +41.7% speedup)
      - Otherwise (non-4K Intel, AMD, NVIDIA, CPU):
        -> 1.0 (reference native canvas)
    - Fallback: 1.0 if unrecognized.
    """
    try:
        if isinstance(user_option, (int, float)):
            if abs(user_option - 0.75) < 1e-4:
                return 0.75, "[INTEL] HUD resolution policy: MANUAL 75%" if encoder == "intel" else ""
            if abs(user_option - 0.5) < 1e-4:
                return 0.5, "[INTEL] HUD resolution policy: MANUAL 50%" if encoder == "intel" else ""
            if abs(user_option - 1.0) < 1e-4:
                return 1.0, "[INTEL] HUD resolution policy: MANUAL 100%" if encoder == "intel" else ""

        opt_str = str(user_option).strip() if user_option is not None else "Auto"
        if opt_str == "75%":
            return 0.75, "[INTEL] HUD resolution policy: MANUAL 75%" if encoder == "intel" else ""
        if opt_str == "50%":
            return 0.5, "[INTEL] HUD resolution policy: MANUAL 50%" if encoder == "intel" else ""
        if opt_str == "100%":
            return 1.0, "[INTEL] HUD resolution policy: MANUAL 100%" if encoder == "intel" else ""

        # Auto mode
        if opt_str in ("Auto", "auto", ""):
            if encoder == "intel" and render_w == 3840 and render_h == 2160:
                return 0.75, f"[INTEL] HUD resolution policy: AUTO -> 75% (2560x1440 -> {render_w}x{render_h})"
            elif encoder == "intel":
                return 1.0, f"[INTEL] HUD resolution policy: AUTO -> 100% ({render_w}x{render_h})"
            else:
                return 1.0, ""
    except Exception:
        pass
    return 1.0, "[INTEL] HUD resolution policy: FALLBACK 100%" if encoder == "intel" else ""


def stream_overlay_to_ffmpeg(
    ffmpeg_exe: str,
    input_files: str | list[str],
    output_file: str,
    duration_s: float,
    start_dt_utc: Optional[datetime],
    tz_offset_hours: float,
    speed_samples: list,
    track_samples: list,
    alt_samples: list,
    font_path: str,
    layout: dict[str, Any],
    field_samples: dict[str, Any],
    max_distance_m: float | None = None,
    video_timeline: Optional[Any] = None,
    target_fps: float = 30.0,
    update_rate_step: int = 1,
    workers: Optional[int] = None,
    iso_samples: Optional[list] = None,
    exposure_samples: Optional[list] = None,
    temperature_samples: Optional[list] = None,
    gpx_speed_samples: Optional[list] = None,
    gpx_track_samples: Optional[list] = None,
    gpx_alt_samples: Optional[list] = None,
    gpx_power_samples: Optional[list] = None,
    gpx_atemp_samples: Optional[list] = None,
    gpx_hr_samples: Optional[list] = None,
    gpx_cad_samples: Optional[list] = None,
    fit_data: Optional[dict[str, list]] = None,
    gps_track: Optional[list] = None,
    encoder: str = "nv",
    gpu: int = 0,
    video_bitrate: str = "40M",
    render_w: int = 3840,
    render_h: int = 2160,
    resolution_name: str = "source",
    rotation_degrees: int = 0,
    container_rotation: int = 0,
    overlay_w: int = 3840,
    overlay_h: int = 2160,
    hud_resolution_scale: Any = 1.0,
    progress_cb: Optional[Callable] = None,
    on_render_progress: Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
    active_process_holder: Optional[dict] = None,
) -> int:
    """Stream rendered overlay frames into an FFmpeg process."""
    hud_resolution_scale, policy_msg = resolve_hud_resolution_policy(
        encoder=encoder,
        render_w=render_w,
        render_h=render_h,
        user_option=hud_resolution_scale,
    )
    if policy_msg:
        print(policy_msg, flush=True)

    if hud_resolution_scale != 1.0:
        # Direct callers may not precompute overlay_w/overlay_h. For the
        # scaled modes the export canvas is the source of truth.
        if render_w == 3840 and render_h == 2160 and abs(hud_resolution_scale - 0.75) < 1e-4:
            overlay_w = 2560
            overlay_h = 1440
        else:
            overlay_w = max(2, int(round(render_w * hud_resolution_scale)))
            overlay_h = max(2, int(round(render_h * hud_resolution_scale)))
        if overlay_w % 2:
            overlay_w += 1
        if overlay_h % 2:
            overlay_h += 1
    # The caller normally supplies the scaled canvas. Keep this diagnostic at
    # the stream boundary so direct callers are auditable too.
    print(
        f"[HUD Resolution] scale={hud_resolution_scale:.2f} "
        f"canvas={overlay_w}x{overlay_h} output={render_w}x{render_h}",
        flush=True,
    )

    if encoder == "intel":
        # INTEL_FORCE: strictly require a usable Intel GPU + QSV.  No silent
        # cross-GPU fallback (NVIDIA/AMD/CUDA/NVENC/AMF) and no silent CPU
        # fallback.  On failure resolve_intel_force raises IntelBackendError,
        # which intentionally stops the Intel backend initialisation.
        intel_resolution = resolve_intel_force(ffmpeg_exe=ffmpeg_exe)
        intel_selection = intel_device_selection(intel_resolution)

    t_prod_start = time.perf_counter()
    # ETAP 4A0: opt-in pipeline audit is also available for the Intel
    # CPU_REFERENCE path so FULL_CANVAS vs REGION transport can be measured.
    # Inert unless TELEM_PIPELINE_AUDIT is enabled; NVIDIA behaviour unchanged.
    pipeline_audit = PipelineAuditRecorder() if encoder in ("nv", "intel") and env_enabled() else None
    if pipeline_audit is not None:
        pipeline_audit.start(time.perf_counter_ns())
    t_prep_start = t_prod_start
    BenchmarkTracker.get_instance().enable(True)

    phase_t0 = time.time()
    cut_regions = layout.get("cut_regions", [])

    generation_fps = target_fps / update_rate_step
    total_overlay_frames = max(1, math.ceil(duration_s * generation_fps))
    _report_phase(on_render_progress, "prep", 0.05, "Przygotowywanie HUD...", time.time() - phase_t0)

    # ── ETAP 4B: multi-file render diagnostics (once per export) ──────────
    is_multi_file = (
        video_timeline is not None
        and getattr(video_timeline, "clip_count", 0) > 1
    )
    if is_multi_file:
        print("[MultiFile Render]", flush=True)
        print(
            f"clips={video_timeline.clip_count} "
            f"global_duration={duration_s:.3f}", flush=True,
        )
        for i, clip in enumerate(video_timeline.clips, start=1):
            abs_start = (
                clip.absolute_start_dt.isoformat(timespec="milliseconds")
                if clip.absolute_start_dt else "N/A"
            )
            abs_end = (
                clip.absolute_end_dt.isoformat(timespec="milliseconds")
                if clip.absolute_end_dt else "N/A"
            )
            print(
                f"clip {i}/{video_timeline.clip_count} "
                f"global={clip.global_start_s:.3f}-{clip.global_end_s:.3f} "
                f"absolute={abs_start}-{abs_end} "
                f"quality={getattr(clip, 'timestamp_quality', '?')}",
                flush=True,
            )
        for i, clip in enumerate(video_timeline.clips, start=1):
            if getattr(clip, "timestamp_quality", None) == "fallback":
                print(
                    f"[MultiFile Render] WARNING: clip {i} uses fallback absolute "
                    f"timestamp. Telemetry synchronization may be incorrect.",
                    flush=True,
                )

    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])
    enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}
    is_no_hud = not bool(enabled_indicators) and not bool(custom_texts)
    intel_gpu_resident = (
        encoder == "intel"
        and not is_multi_file
        and rotation_degrees == 0
        and container_rotation == 0
        and not bool(cut_regions)
        and not is_no_hud
        and resolution_name in ("source", "720p", "1080p")
        and os.environ.get("TELEM_INTEL_GPU_RESIDENT", "1").strip().lower() not in ("0", "false", "off")
    )
    intel_source_file = (
        input_files if isinstance(input_files, (str, Path))
        else (input_files[0] if len(input_files) == 1 else None)
    )
    if intel_gpu_resident and intel_source_file is not None:
        probe = _probe_intel_native_source(str(intel_source_file), ffmpeg_exe)
        if not probe[0]:
            intel_gpu_resident = False
            print(f"[INTEL] Fallback reason: {probe[1]}", flush=True)
    intel_cpu_download_format = "nv12"
    if encoder == "intel" and not intel_gpu_resident and intel_source_file is not None:
        intel_cpu_download_format = _probe_intel_cpu_download_format(str(intel_source_file), ffmpeg_exe)
        print(f"[INTEL] CPU_REFERENCE download format: {intel_cpu_download_format}", flush=True)
    intel_cpu_software_decode = (
        encoder == "intel" and not intel_gpu_resident
        and intel_cpu_download_format == "p010le"
    )
    if encoder == "intel":
        print(
            f"[INTEL] Render path: {'D3D11_NATIVE' if intel_gpu_resident else 'CPU_REFERENCE'}",
            flush=True,
        )
        print(
            f"[INTEL] Video frame residency: {'GPU' if intel_gpu_resident else 'CPU_REFERENCE'}",
            flush=True,
        )
        if intel_gpu_resident:
            print("[INTEL] Overlay source: CPU_RGBA_UPLOAD", flush=True)
        if not intel_gpu_resident and intel_cpu_software_decode:
            print("[INTEL] Fallback reason: unsupported native vertical-slice configuration", flush=True)
            print("[INTEL] Decode path: SOFTWARE", flush=True)
            print(f"[INTEL] CPU working format: {'10-bit' if intel_cpu_download_format == 'p010le' else '8-bit'}", flush=True)
            print("[INTEL] HWDownload used: NO", flush=True)
        elif not intel_gpu_resident:
            print("[INTEL] Fallback reason: unsupported native vertical-slice configuration", flush=True)
            print("[INTEL] Decode path: QSV/D3D11VA", flush=True)
            print(f"[INTEL] CPU working format: {'10-bit' if intel_cpu_download_format == 'p010le' else '8-bit'}", flush=True)
            print("[INTEL] HWDownload used: YES", flush=True)

        # ETAP 4K: single bitrate source of truth + one-shot RC contract
        # diagnostics (GUI video_bitrate wins unless the diagnostic env
        # override TELEM_INTEL_QSV_BITRATE_MBPS is set; Intel-only).
        video_bitrate, intel_rc_source = resolve_intel_qsv_bitrate(
            video_bitrate)
        print("[INTEL] QSV encoder: HEVC", flush=True)
        print("[INTEL] QSV preset: veryfast", flush=True)
        print(f"[INTEL] QSV rate-control source: {intel_rc_source}",
              flush=True)
        print(f"[INTEL] QSV target bitrate: {video_bitrate}", flush=True)
        print("[INTEL] QSV look_ahead: 0 | async_depth: 4", flush=True)

    # ── ETAP 4B: AMD_NATIVE_D3D11 multi-file guard ────────────────────────
    # amd_native_exporter uses only input_files[0]; do NOT silently render a
    # partial movie.  For multi-file the standard AMD (AMF) pipeline — which
    # uses the shared FFmpeg concat + timeline — remains allowed; only the
    # AMD_NATIVE_D3D11 exporter is skipped.
    amd_native_multi_guard = False
    if encoder in ("amd", "amd_native") and is_multi_file:
        print(
            "[MultiFile] AMD_NATIVE_D3D11 multi-file not yet supported "
            "-> falling back to standard AMD/AMF pipeline",
            flush=True,
        )
        amd_native_multi_guard = True

    if encoder in ("amd", "amd_native") and not amd_native_multi_guard:
        from src.ffmpeg.detection import detect_amd_compose_backend
        if detect_amd_compose_backend("AUTO", ffmpeg_exe=ffmpeg_exe) == "AMD_NATIVE_D3D11":
            from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
            from src.ffmpeg.command_builder import RESOLUTION_MAP
            target_res = RESOLUTION_MAP.get(resolution_name)
            out_w, out_h = target_res if target_res is not None else (render_w, render_h)
            print("[STREAM AMD] Dispatching to production AMD_NATIVE_D3D11 GPU pipeline...", flush=True)
            success = export_amd_native_d3d11(
                ffmpeg_exe=ffmpeg_exe,
                input_files=input_files,
                output_file=str(output_file),
                duration_s=duration_s,
                video_width=out_w,
                video_height=out_h,
                start_dt_utc=start_dt_utc,
                tz_offset_hours=tz_offset_hours,
                speed_samples=speed_samples,
                track_samples=track_samples,
                alt_samples=alt_samples,
                font_path=font_path,
                layout=layout,
                field_samples=field_samples,
                target_fps=target_fps,
                video_bitrate=video_bitrate,
                max_distance_m=max_distance_m,
                iso_samples=iso_samples,
                exposure_samples=exposure_samples,
                temperature_samples=temperature_samples,
                gpx_speed_samples=gpx_speed_samples,
                gpx_track_samples=gpx_track_samples,
                gpx_alt_samples=gpx_alt_samples,
                gpx_power_samples=gpx_power_samples,
                gpx_atemp_samples=gpx_atemp_samples,
                gpx_hr_samples=gpx_hr_samples,
                gpx_cad_samples=gpx_cad_samples,
                fit_data=fit_data,
                gps_track=gps_track,
                progress_cb=progress_cb,
                on_render_progress=on_render_progress,
                cancel_event=cancel_event,
                active_process_holder=active_process_holder,
            )
            if success:
                return total_overlay_frames
            if cancel_event is not None and cancel_event.is_set():
                return 0
            print("[STREAM AMD] Native AMD_NATIVE_D3D11 export returned False. Falling back to software exporter...", flush=True)

    if encoder == "nv" and not is_no_hud:
        # ETAP 5B.5: keep the persisted/user layout unchanged and snap only the
        # runtime NVIDIA composition anchors. This is deliberately after the
        # AMD dispatch so other backends retain their existing geometry.
        layout = _snap_nvidia_hud_layout(layout, overlay_w, overlay_h, NVIDIA_HUD_GRID_PX)
        cut_regions = layout.get("cut_regions", [])
        indicators = layout.get("indicators", {})
        custom_texts = layout.get("custom_texts", [])
        enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}
        is_no_hud = not bool(enabled_indicators) and not bool(custom_texts)

    hud_x, hud_y = 0, 0
    stream_w, stream_h = overlay_w, overlay_h
    hud_bbox: tuple[int, int, int, int] | None = None
    hud_regions: list[tuple[int, int, int, int, int, int]] | None = None

    if encoder == "intel" and not is_no_hud and _intel_hud_region_gate(
        intel_gpu_resident, rotation_degrees, container_rotation, encoder):
        # ETAP 4B: bbox crop + threshold decision lives in the unit-tested
        # _intel_hud_region_decision(). The shared layout bbox stays
        # deliberately conservative (glyph bearings, outlines, shadows,
        # rotating/gauge geometry) and the rectangle is expanded outward to
        # even coordinates/dimensions required by common YUV/D3D11 surfaces.
        hud_x, hud_y, stream_w, stream_h, ratio, mode = \
            _intel_hud_region_decision(layout, overlay_w, overlay_h)
        full_area = overlay_w * overlay_h
        threshold_txt = os.environ.get(
            "TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO", "0.85")
        if mode == "region":
            hud_bbox = (hud_x, hud_y, stream_w, stream_h)
            print("[INTEL] HUD upload path: REGION", flush=True)
        elif mode == "full_threshold":
            stream_w, stream_h = overlay_w, overlay_h
            print(f"[INTEL] HUD upload path: FULL_CANVAS "
                  f"reason=ratio_above_threshold({ratio:.3f}>={threshold_txt})",
                  flush=True)
        else:
            stream_w, stream_h = overlay_w, overlay_h
            print("[INTEL] HUD upload path: FULL_CANVAS "
                  "reason=empty_bbox_geometry", flush=True)
        print(f"[INTEL] HUD bbox ratio: {max(0.0, min(1.0, ratio)):.3f}", flush=True)
        print(f"[INTEL] threshold: {threshold_txt}", flush=True)
        print(f"[INTEL] HUD full canvas: {overlay_w}x{overlay_h}", flush=True)
        print(f"[INTEL] HUD region: x={hud_x} y={hud_y} w={stream_w} h={stream_h}", flush=True)
        upload_bytes = stream_w * stream_h * 4
        full_bytes = full_area * 4
        reduction = 100.0 * (1.0 - upload_bytes / full_bytes) if full_bytes else 0.0
        print(f"[INTEL] HUD upload bytes/frame: {upload_bytes}", flush=True)
        print(f"[INTEL] HUD transfer reduction: {reduction:.1f}%", flush=True)

    if encoder == "amd" and not is_no_hud:
        stream_w, stream_h, hud_regions = get_layout_hud_regions(layout, overlay_w, overlay_h, max_regions=3)
        if len(hud_regions) == 1:
            hud_x, hud_y = hud_regions[0][0], hud_regions[0][1]
            stream_w, stream_h = hud_regions[0][4], hud_regions[0][5]
            hud_bbox = (hud_x, hud_y, stream_w, stream_h)
            hud_regions = None
            print(
                f"[STREAM AMD] Single HUD sub-window: {stream_w}x{stream_h} at ({hud_x},{hud_y}) "
                f"({(stream_w*stream_h*4)/(1024*1024):.1f} MB vs {(overlay_w*overlay_h*4)/(1024*1024):.1f} MB)",
                flush=True,
            )
        else:
            hud_bbox = None
            print(
                f"[STREAM AMD] Multi-Region HUD Atlas: {len(hud_regions)} regions, Atlas {stream_w}x{stream_h} "
                f"({(stream_w*stream_h*4)/(1024*1024):.1f} MB vs {(overlay_w*overlay_h*4)/(1024*1024):.1f} MB)",
                flush=True,
            )
    elif encoder == "nv" and not is_no_hud:
        text_bbox_context = build_text_bbox_context(
            layout,
            fit_data=fit_data,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temperature_samples,
            gpx_speed_samples=gpx_speed_samples,
            gpx_track_samples=gpx_track_samples,
            gpx_alt_samples=gpx_alt_samples,
            gpx_power_samples=gpx_power_samples,
            gpx_atemp_samples=gpx_atemp_samples,
            gpx_hr_samples=gpx_hr_samples,
            gpx_cad_samples=gpx_cad_samples,
        )
        phantom_keys = text_bbox_context["phantom_keys"]
        if phantom_keys:
            print(f"[NVIDIA] Transport phantom bbox excluded: {sorted(phantom_keys)}", flush=True)

        # 1. Global BBox
        bx, by, bw, bh = get_layout_hud_bbox(layout, overlay_w, overlay_h)
        full_area = overlay_w * overlay_h
        global_bbox_area = bw * bh
        global_area_pct = (global_bbox_area / full_area) * 100.0

        # 2. Multi-Region Atlas (ETAP 5B.5: up to 4 regions)
        atlas_w, atlas_h, candidate_regions = get_layout_hud_regions(
            layout, overlay_w, overlay_h, max_regions=NVIDIA_HUD_MAX_REGIONS,
            text_candidates=text_bbox_context["text_candidates"],
            phantom_keys=phantom_keys,
            font_path=font_path,
        )
        atlas_area = atlas_w * atlas_h
        atlas_area_pct = (atlas_area / full_area) * 100.0

        print(f"[NVIDIA] HUD global bbox: {bw}x{bh} / {global_area_pct:.1f}%", flush=True)

        if len(candidate_regions) == 1 or (global_area_pct <= 85.0 and global_bbox_area <= atlas_area):
            # A. SINGLE BBOX
            hud_x, hud_y = bx, by
            stream_w, stream_h = bw, bh
            hud_bbox = (hud_x, hud_y, stream_w, stream_h)
            hud_regions = None
            slot_mb = (stream_w * stream_h * 4) / (1024 * 1024)
            shm_total_mb = slot_mb * 8
            reduction_pct = 100.0 - global_area_pct
            print(f"[NVIDIA] HUD mode: SINGLE_BBOX", flush=True)
            print(f"[NVIDIA] HUD bbox: x={hud_x} y={hud_y} w={stream_w} h={stream_h}", flush=True)
            print(f"[NVIDIA] HUD area: {global_area_pct:.1f}% of {overlay_w}x{overlay_h}", flush=True)
            print(f"[NVIDIA] HUD slot: {slot_mb:.2f} MB", flush=True)
            print(f"[NVIDIA] HUD SHM total: {shm_total_mb:.1f} MB", flush=True)
            print(f"[NVIDIA] HUD transport reduction: {reduction_pct:.1f}%", flush=True)

        elif atlas_area_pct <= 70.0:
            # B. MULTI-REGION ATLAS (at least 30% reduction)
            hud_bbox = None
            hud_regions = candidate_regions
            layout["_nvidia_direct_region"] = True
            layout["_nvidia_phantom_keys"] = tuple(sorted(phantom_keys))
            layout["_nvidia_atlas_size"] = (atlas_w, atlas_h)
            print("[NVIDIA] HUD producer: DIRECT_REGION", flush=True)
            hud_x, hud_y = 0, 0
            stream_w, stream_h = atlas_w, atlas_h
            slot_mb = (stream_w * stream_h * 4) / (1024 * 1024)
            shm_total_mb = slot_mb * 8
            reduction_pct = 100.0 - atlas_area_pct
            print(f"[NVIDIA] HUD mode: MULTI_REGION_ATLAS", flush=True)
            print(f"[NVIDIA] HUD regions: {len(hud_regions)}", flush=True)
            for i, r in enumerate(hud_regions):
                print(f"[NVIDIA] Region {i}: src=({r[0]},{r[1]},{r[4]}x{r[5]}) atlas=({r[2]},{r[3]})", flush=True)
            print(f"[NVIDIA] HUD atlas: {stream_w}x{stream_h}", flush=True)
            print(f"[NVIDIA] HUD atlas area: {atlas_area_pct:.1f}% of {overlay_w}x{overlay_h}", flush=True)
            print(f"[NVIDIA] HUD atlas slot: {slot_mb:.2f} MB", flush=True)
            print(f"[NVIDIA] HUD atlas SHM total: {shm_total_mb:.1f} MB", flush=True)
            print(f"[NVIDIA] HUD transport reduction: {reduction_pct:.1f}%", flush=True)

        else:
            # C. FULL FRAME FALLBACK
            hud_bbox = None
            hud_regions = None
            hud_x, hud_y = 0, 0
            stream_w, stream_h = overlay_w, overlay_h
            full_slot_mb = (overlay_w * overlay_h * 4) / (1024 * 1024)
            full_shm_mb = full_slot_mb * 8
            print(f"[NVIDIA] HUD mode: FULL_FRAME (fallback: atlas {atlas_area_pct:.1f}% > 70%)", flush=True)
            print(f"[NVIDIA] HUD slot: {full_slot_mb:.2f} MB", flush=True)
            print(f"[NVIDIA] HUD SHM total: {full_shm_mb:.1f} MB", flush=True)
            print(f"[NVIDIA] HUD transport reduction: 0.0%", flush=True)

    _report_phase(on_render_progress, "prep", 0.45, "Przygotowywanie HUD...", time.time() - phase_t0)

    effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees
    nv_rot180_cuda = is_nv_rot180_cuda(encoder, rotation_degrees, container_rotation)
    t_worker_init_start = time.perf_counter()
    t_prep_end = t_worker_init_start
    init_worker(
        overlay_w, overlay_h, font_path, layout, field_samples, max_distance_m,
        iso_samples, exposure_samples, temperature_samples,
        gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
        gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
        fit_data,
        gps_track,
        start_dt_utc, tz_offset_hours,
        speed_samples, track_samples, alt_samples,
        target_fps, update_rate_step, total_overlay_frames,
        cut_regions=cut_regions,
        effective_rotation=effective_rotation,
        hud_bbox=hud_bbox,
        hud_regions=hud_regions,
        hud_rotate_180=nv_rot180_cuda,
        video_timeline=video_timeline,
    )

    if cancel_event is not None and cancel_event.is_set():
        return 0

    _report_phase(on_render_progress, "prep", 0.70, "Przygotowywanie HUD...", time.time() - phase_t0)

    # Build FFmpeg input args
    if encoder == "intel":
        # Do not use generic multi-GPU probing for INTEL_FORCE.
        intel_cpu_software_decode = (
            not intel_gpu_resident and intel_cpu_download_format == "p010le"
        )
        hwaccel = None if intel_cpu_software_decode else "qsv"
        full_intel_device_args = intel_ffmpeg_device_args(intel_selection)
        if not intel_cpu_software_decode:
            intel_device_args = full_intel_device_args
        else:
            # CPU_REFERENCE HDR fallback: do not submit decoded frames to QSV.
            # Keep only device creation and qsv_device so the encoder remains
            # pinned to the selected Intel adapter.
            intel_device_args = []
            for i, arg in enumerate(full_intel_device_args):
                if arg in ("-init_hw_device", "-qsv_device"):
                    intel_device_args.extend(full_intel_device_args[i:i + 2])
        # qsv_device is an encoder option in this FFmpeg build and takes the
        # DirectX adapter index, not the named qsv device.
    else:
        hwaccel = detect_gpu_decoder(encoder, ffmpeg_exe=ffmpeg_exe)
        intel_device_args = []
        intel_cpu_software_decode = False
    # Manual rotation uses CPU filters (vflip/transpose) which cannot take
    # hardware frames, so decoded frames must stay in system memory in that case.
    needs_cpu_rotation = rotation_degrees in (90, 180, 270)
    if nv_rot180_cuda:
        # NVIDIA rotation=180: handled on the CUDA fast-path (HUD rotated in
        # Python), so the NVIDIA branch is not forced back to the CPU chain.
        needs_cpu_rotation = False
    if encoder == "amd" and needs_cpu_rotation:
        hwaccel = None
    input_args: list[str] = []
    audio_input_args: list[str] = []
    if intel_device_args:
        input_args.extend(intel_device_args)
        if intel_gpu_resident:
            input_args.extend(["-filter_hw_device", intel_selection.qsv_device_name])
    elif hwaccel:
        input_args.extend(["-hwaccel", hwaccel])
        if hwaccel == "cuda" and encoder == "nv" and not needs_cpu_rotation:
            input_args.extend(["-hwaccel_output_format", "cuda"])
    if isinstance(input_files, list) and len(input_files) > 1:
        concat_txt = Path(output_file).parent / "render_concat_list.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in input_files:
                escaped_p = str(p.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_p}'\n")
        input_args.extend(["-f", "concat", "-safe", "0", "-i", str(concat_txt)])
        audio_input_args.extend(["-f", "concat", "-safe", "0", "-i", str(concat_txt)])
    else:
        input_file = input_files[0] if isinstance(input_files, list) else input_files
        if container_rotation != 0 and encoder != "intel":
            # ETAP 5D rotation contract: the Intel pipeline relies on FFmpeg
            # autorotate (display matrix applied at decode) and does NOT bake
            # manual flips -- baking while the MP4 display matrix is still
            # copied to the output produced double-rotated final files.
            # NVIDIA/AMD/CPU keep the previous -noautorotate + manual transform
            # contract untouched.
            input_args.extend(["-noautorotate", "-i", str(input_file)])
        else:
            input_args.extend(["-i", str(input_file)])
        audio_input_args.extend(["-i", str(input_file)])

    use_gpu_compositor = bool(layout.get("_use_gpu_compositor", False))

    # NVIDIA rotation=180 production log — exactly one readable line.
    if encoder == "nv" and effective_rotation == 180:
        if nv_rot180_cuda:
            print("[NVIDIA] ROT180 CUDA FAST PATH", flush=True)
        else:
            print("[NVIDIA] ROT180 CPU FALLBACK", flush=True)

    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe, input_args, output_file,
        overlay_w, overlay_h, stream_w, stream_h, generation_fps,
        encoder, gpu, video_bitrate,
        render_w, render_h, resolution_name,
        container_rotation, rotation_degrees,
        hwaccel=hwaccel,
        cut_regions=cut_regions,
        audio_input_args=audio_input_args,
        hud_x=hud_x,
        hud_y=hud_y,
        is_no_hud=is_no_hud,
        hud_regions=hud_regions,
        use_gpu_compositor=use_gpu_compositor,
        intel_gpu_resident=intel_gpu_resident,
        intel_cpu_download_format=intel_cpu_download_format,
        intel_cpu_software_decode=intel_cpu_software_decode,
    )

    print("FFmpeg streaming cmd:", " ".join(map(str, cmd)), flush=True)
    print(
        f"[STREAM] overlay={stream_w}x{stream_h} at ({hud_x},{hud_y})  render={render_w}x{render_h}  "
        f"gen_fps={generation_fps}  frames={total_overlay_frames}",
        flush=True,
    )
    if encoder == "intel":
        hud_bytes_per_frame = int(stream_w) * int(stream_h) * 4
        print(f"[INTEL] HUD upload bytes/frame: {hud_bytes_per_frame}", flush=True)
    print(f"[STREAM] filter: {filter_complex}", flush=True)

    if filter_complex.startswith("direct_gpu_passthrough"):
        print(f"[STREAM AMD] Direct GPU-resident passthrough (NO HUD mode, zero hwdownload, zero pipe write)", flush=True)
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, startupinfo=startupinfo
        )
        if active_process_holder is not None:
            active_process_holder["process"] = process

        for line in process.stdout:
            if cancel_event is not None and cancel_event.is_set():
                _stop_ffmpeg_process(process)
                break
        if process.poll() is None:
            _wait_process_bounded(process, 10.0)
        if active_process_holder is not None:
            active_process_holder["process"] = None
        return total_overlay_frames

    # Start FFmpeg
    t_ffmpeg_start = time.perf_counter()
    t_worker_init_pre_end = t_ffmpeg_start
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    process = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, universal_newlines=True,
        startupinfo=startupinfo,
    )
    if active_process_holder is not None:
        active_process_holder["process"] = process

    # ── Async stdout reader thread (prevents FFmpeg stdout buffer deadlock) ──
    stdout_lines: list[str] = []

    def _stdout_reader() -> None:
        try:
            for line in process.stdout:
                stdout_lines.append(line.strip())
        except Exception:
            pass

    stdout_t = threading.Thread(target=_stdout_reader, daemon=True)
    stdout_t.start()

    _report_phase(on_render_progress, "prep", 1.0, "Renderowanie klatek...", time.time() - phase_t0)

    start_time = time.time()
    total_piped = 0
    cpu_n = os.cpu_count() or 1
    if workers is None:
        if encoder == "nv":
            workers = max(1, min(4, cpu_n))
        else:
            workers = max(1, cpu_n - 1)
    n_workers = min(workers, total_overlay_frames)

    # Frame size in bytes: RGBA = 4 bytes per pixel
    frame_size = stream_w * stream_h * 4

    shm_pool: SharedFramePool | None = None
    if n_workers > 1:
        # Number of SHM slots: enough to keep workers busy + reorder buffer
        MAX_IN_FLIGHT = max(4, n_workers * 2)
        if pipeline_audit is not None:
            override = os.environ.get("TELEM_AUDIT_MAX_IN_FLIGHT", "").strip()
            if override:
                try:
                    MAX_IN_FLIGHT = max(1, int(override))
                except ValueError:
                    pass
        n_shm_slots = MAX_IN_FLIGHT
        shm_pool = SharedFramePool(n_shm_slots, frame_size)
    else:
        MAX_IN_FLIGHT = 1
        n_shm_slots = 1

    # ── Async pipe writer (background thread) ───────────────────────────
    writer_stats = {
        "first_frame_time": None, "last_frame_time": None, "frames_written": 0,
    }
    if pipeline_audit is not None:
        writer_stats.update({
            "idle_wait_ns": 0, "busy_write_ns": 0,
            "requested_bytes": 0, "returned_bytes": 0, "write_calls": 0,
            "partial_write_frames": 0,
        })
    pipe_queue: queue.Queue = queue.Queue(maxsize=max(8, n_workers * 2))
    pipe_done = threading.Event()
    writer_failed = threading.Event()
    writer_discard_pending = threading.Event()
    writer_t = threading.Thread(
        target=_pipe_writer_thread,
        args=(pipe_queue, process.stdin.buffer, pipe_done, shm_pool, writer_stats, pipeline_audit, writer_failed,
              writer_discard_pending),
        daemon=True,
    )
    writer_t.start()
    t_ffmpeg_started = time.perf_counter()
    cancel_started: float | None = None

    def _note_cancel() -> float:
        nonlocal cancel_started
        if cancel_started is None:
            cancel_started = time.perf_counter()
            _cancel_log("requested", cancel_started, process)
        return cancel_started

    def _put_frame(item: Any) -> bool:
        """Put one frame without allowing cancellation to wait on a full queue."""
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _note_cancel()
                return False
            if writer_failed.is_set():
                print("[STREAM] FFmpeg stdin writer failed; stopping frame producer", flush=True)
                return False
            try:
                pipe_queue.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue

    try:
        if n_workers <= 1:
            # Single worker — no IPC, direct rendering
            for i in range(total_overlay_frames):
                if cancel_event is not None and cancel_event.is_set():
                    _note_cancel()
                    break
                _, raw_bytes = render_frame_bytes_job((i,))
                if not _put_frame(raw_bytes):
                    break
                total_piped += 1
                if total_piped % 50 == 0 or total_piped == total_overlay_frames:
                    _report_stream_progress(total_piped, total_overlay_frames, start_time, progress_cb, on_render_progress, target_fps, pipeline_audit)
        else:
            from concurrent.futures import wait, FIRST_COMPLETED

            shm_names = shm_pool.shm_names()

            telemetry_cache = None
            try:
                from src.telemetry_precompute import build_telemetry_cache
                from src.overlay_renderer import build_chart_data
                from src.ffmpeg.worker_cache import _resolve_cache_value, _resolve_cache_samples

                t_pre_start = time.perf_counter()
                
                # Precompute static ranges
                _range_cache = {}
                _range_cache["max_distance_m"] = max_distance_m
                
                indic = layout.get("indicators", {})
                spd_ind = indic.get("speed_visual") or indic.get("speed_text") or indic.get("fit_speed_text") or indic.get("fit_enhanced_speed_text") or {}
                spd_src = spd_ind.get("source", "fit" if ("fit_speed_text" in indic or "fit_enhanced_speed_text" in indic) else "gpmf")
                if spd_src == "gpx":
                    spd_for_range = gpx_speed_samples
                elif spd_src == "fit":
                    spd_for_range = fit_data.get("speed", []) if fit_data else []
                else:
                    spd_for_range = speed_samples
                if spd_for_range:
                    spd_vals = [s for _, s in spd_for_range]
                    _range_cache["max_speed_kmh"] = max(spd_vals) if spd_vals else None
                else:
                    _range_cache["max_speed_kmh"] = None

                alt_ind = indic.get("alt_visual") or indic.get("alt_text") or indic.get("fit_altitude_text") or indic.get("fit_enhanced_altitude_text") or {}
                alt_src = alt_ind.get("source", "fit" if ("fit_altitude_text" in indic or "fit_enhanced_altitude_text" in indic) else "gpmf")
                if alt_src == "gpx":
                    alt_for_range = gpx_alt_samples
                elif alt_src == "fit":
                    alt_for_range = fit_data.get("alt", []) if fit_data else []
                else:
                    alt_for_range = alt_samples
                if alt_for_range:
                    alts = [a for _, a in alt_for_range]
                    _range_cache["min_alt"] = min(alts) if alts else None
                    _range_cache["max_alt"] = max(alts) if alts else None
                else:
                    _range_cache["min_alt"] = None
                    _range_cache["max_alt"] = None

                duration_s = (total_overlay_frames / target_fps) if (total_overlay_frames and target_fps) else None
                # ETAP 4B: with a multi-file timeline the telemetry/chart range
                # is the REAL absolute end (max clip absolute_end), never
                # start_dt_utc + project_duration (wrong with large gaps).
                end_dt_utc = None
                if video_timeline is not None and getattr(video_timeline, "clip_count", 0):
                    end_dt_utc = timeline_absolute_end(video_timeline)
                if end_dt_utc is None and start_dt_utc and duration_s:
                    end_dt_utc = start_dt_utc + timedelta(seconds=duration_s)
                source_ranges = {}
                if fit_data:
                    all_fit_pts = [s for s in fit_data.values() if s]
                    if all_fit_pts:
                        source_ranges["fit"] = (
                            min(s[0][0] for s in all_fit_pts),
                            max(s[-1][0] for s in all_fit_pts),
                        )
                
                def _get_src_samples(src_name: str) -> tuple[list, list, list]:
                    if src_name == "gpx":
                        return (gpx_speed_samples or [], gpx_track_samples or [], gpx_alt_samples or [])
                    if src_name == "fit":
                        fit_d = fit_data or {}
                        return (fit_d.get("speed", []), fit_d.get("track", []), fit_d.get("alt", []))
                    return (speed_samples or [], track_samples or [], alt_samples or [])

                def _resolve_stream_samples(field_name: str, source: str = "fit", indicator_key: str | None = None) -> list:
                    if source == "fit":
                        fit_d = fit_data or {}
                        aliases = {
                            "power": ("power", "curVpower"), "hr": ("hr", "heart_rate"),
                            "cad": ("cad", "cadence"), "atemp": ("atemp", "temperature"),
                            "battery": ("battery", "battery_soc"),
                        }.get(field_name, (field_name,))
                        for name in aliases:
                            if fit_d.get(name):
                                return list(fit_d[name])
                        return []
                    if source == "gpx":
                        gpx_map = {
                            "speed": gpx_speed_samples, "alt": gpx_alt_samples, "altitude": gpx_alt_samples,
                            "dist": gpx_track_samples, "track": gpx_track_samples, "power": gpx_power_samples,
                            "atemp": gpx_atemp_samples, "hr": gpx_hr_samples, "cad": gpx_cad_samples,
                        }
                        return list(gpx_map.get(field_name, []) or [])
                    if source == "gpmf":
                        gpmf_map = {
                            "speed": speed_samples, "alt": alt_samples, "altitude": alt_samples,
                            "dist": track_samples, "track": track_samples, "iso": iso_samples,
                            "exposure": exposure_samples, "temperature": temperature_samples,
                        }
                        return list(gpmf_map.get(field_name, []) or [])
                    return []

                chart_data = build_chart_data(
                    layout,
                    _get_src_samples,
                    _resolve_stream_samples,
                    start_dt_utc=start_dt_utc, end_dt_utc=end_dt_utc,
                    source_activity_ranges=source_ranges,
                )

                telemetry_cache = build_telemetry_cache(
                    layout=layout,
                    base_dt=start_dt_utc,
                    tz_offset_hours=tz_offset_hours or 0.0,
                    start_dt_utc=start_dt_utc,
                    speed_samples=speed_samples or [],
                    track_samples=track_samples or [],
                    alt_samples=alt_samples or [],
                    iso_samples=iso_samples or [],
                    exposure_samples=exposure_samples or [],
                    temperature_samples=temperature_samples or [],
                    gpx_speed_samples=gpx_speed_samples or [],
                    gpx_track_samples=gpx_track_samples or [],
                    gpx_alt_samples=gpx_alt_samples or [],
                    gpx_power_samples=gpx_power_samples or [],
                    gpx_atemp_samples=gpx_atemp_samples or [],
                    gpx_hr_samples=gpx_hr_samples or [],
                    gpx_cad_samples=gpx_cad_samples or [],
                    fit_data=fit_data,
                    gps_track=gps_track,
                    chart_data=chart_data,
                    resolve_cache_value=_resolve_cache_value,
                    _range_cache=_range_cache,
                    total_frames=total_overlay_frames,
                    target_fps=target_fps or 29.97,
                    video_timeline=video_timeline,
                    update_rate_step=update_rate_step,
                )
                t_pre_build = time.perf_counter() - t_pre_start
                stats = telemetry_cache.stats()
                cache_mb = stats["memory_mib"]
                n_fields = len(telemetry_cache.static.fit_keys) + len(telemetry_cache.static.dynamic_keys) + 8
                if encoder == "nv":
                    print(f"[NVIDIA] Telemetry mode: PRECOMPUTED", flush=True)
                    print(f"[NVIDIA] Telemetry frames: {total_overlay_frames}", flush=True)
                    print(f"[NVIDIA] Telemetry fields: {n_fields}", flush=True)
                    print(f"[NVIDIA] Telemetry cache: {cache_mb:.2f} MB", flush=True)
                    print(f"[NVIDIA] Telemetry precompute build: {t_pre_build:.3f} s", flush=True)
                else:
                    print(f"[STREAM] Telemetry mode: PRECOMPUTED ({total_overlay_frames} frames, {cache_mb:.2f} MB, {t_pre_build*1000:.1f} ms)", flush=True)
            except Exception as exc:
                if encoder == "nv":
                    print(f"[NVIDIA] Telemetry precompute unavailable: {exc}", flush=True)
                    print(f"[NVIDIA] Falling back to live telemetry resolver", flush=True)
                else:
                    print(f"[STREAM] Telemetry precompute unavailable: {exc} -> live resolver fallback", flush=True)
                telemetry_cache = None

            init_args = (
                overlay_w, overlay_h, font_path, layout, field_samples, max_distance_m,
                iso_samples, exposure_samples, temperature_samples,
                gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
                gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
                fit_data,
                gps_track,
                start_dt_utc, tz_offset_hours,
                speed_samples, track_samples, alt_samples,
                target_fps, update_rate_step, total_overlay_frames,
                cut_regions, effective_rotation, hud_bbox, hud_regions,
                nv_rot180_cuda,
                telemetry_cache,
                video_timeline,
            )

            if encoder == "nv":
                print(
                    f"[NVIDIA] Overlay workers: {n_workers} | MAX_IN_FLIGHT: {MAX_IN_FLIGHT} | "
                    f"SHM: ~{n_shm_slots * frame_size / 1024 / 1024:.0f} MB ({n_shm_slots} slots × {frame_size / 1024 / 1024:.1f} MB)",
                    flush=True,
                )
            else:
                print(
                    f"[STREAM] SHM pool: {n_shm_slots} slots × {frame_size / 1024 / 1024:.1f} MB = "
                    f"{n_shm_slots * frame_size / 1024 / 1024:.0f} MB total | "
                    f"workers={n_workers} | MAX_IN_FLIGHT={MAX_IN_FLIGHT}",
                    flush=True,
                )

            with _RenderExecutor(
                max_workers=n_workers,
                initializer=_init_worker_with_shm,
                initargs=(shm_names, frame_size, *init_args),
                cancel_event=cancel_event,
            ) as ex:
                pending: set = set()
                reorder_buf: dict[int, int] = {}  # frame_idx -> shm_slot
                next_idx = 0
                submitted = 0

                def _submit_audited(frame_index: int, slot_index: int):
                    if pipeline_audit is not None:
                        pipeline_audit.frame(frame_index)
                        if pipeline_audit.frame(frame_index).get("frame_scheduled_ns") is None:
                            pipeline_audit.mark(frame_index, "frame_scheduled_ns", time.perf_counter_ns())
                    acquired_ns = time.perf_counter_ns()
                    if pipeline_audit is not None:
                        pipeline_audit.mark(frame_index, "slot_acquired_ns", acquired_ns)
                        pipeline_audit.sample_occupancy(
                            "shm_used", n_shm_slots - shm_pool._free.qsize()
                        )
                        pipeline_audit.mark(frame_index, "submit_started_ns", time.perf_counter_ns())
                    future = ex.submit(
                        render_frame_shm_job,
                        (frame_index, slot_index, True) if pipeline_audit is not None else (frame_index, slot_index),
                    )
                    if pipeline_audit is not None:
                        pipeline_audit.mark(frame_index, "job_submitted_ns", time.perf_counter_ns())
                    return future

                # Fill initial window — acquire SHM slots and submit jobs
                for _ in range(min(MAX_IN_FLIGHT, total_overlay_frames)):
                    if pipeline_audit is not None:
                        pipeline_audit.frame(submitted)
                        pipeline_audit.mark(submitted, "frame_scheduled_ns", time.perf_counter_ns())
                        pipeline_audit.mark(submitted, "in_flight_at_schedule", len(pending) + len(reorder_buf))
                    slot = _acquire_shm_slot(shm_pool, process, stdout_lines, cancel_event=cancel_event)
                    pending.add(_submit_audited(submitted, slot))
                    submitted += 1

                while pending and not (
                    cancel_event is not None and cancel_event.is_set()
                ):
                    done, pending = wait(pending, return_when=FIRST_COMPLETED,
                                         timeout=0.1)
                    for fut in done:
                        future_completed_ns = time.perf_counter_ns()
                        result = fut.result()
                        result_observed_ns = time.perf_counter_ns()
                        if len(result) >= 10:
                            (
                                idx, slot, worker_pid, worker_started_ns,
                                worker_render_started_ns, worker_render_finished_ns,
                                shm_copy_finished_ns, clear_started_ns,
                                clear_finished_ns, zero_copy,
                            ) = result
                            if pipeline_audit is not None:
                                pipeline_audit.mark(idx, "worker_clear_started_ns", clear_started_ns)
                                pipeline_audit.mark(idx, "worker_clear_finished_ns", clear_finished_ns)
                                pipeline_audit.mark(idx, "worker_zero_copy", bool(zero_copy))
                            if pipeline_audit is not None:
                                pipeline_audit.mark(idx, "worker_pid", worker_pid)
                                pipeline_audit.mark(idx, "worker_started_ns", worker_started_ns)
                                pipeline_audit.mark(idx, "worker_render_started_ns", worker_render_started_ns)
                                pipeline_audit.mark(idx, "worker_render_finished_ns", worker_render_finished_ns)
                                pipeline_audit.mark(idx, "shm_copy_finished_ns", shm_copy_finished_ns)
                        elif len(result) >= 7:
                            (
                                idx, slot, worker_pid, worker_started_ns,
                                worker_render_started_ns, worker_render_finished_ns,
                                shm_copy_finished_ns,
                            ) = result
                            if pipeline_audit is not None:
                                pipeline_audit.mark(idx, "worker_pid", worker_pid)
                                pipeline_audit.mark(idx, "worker_started_ns", worker_started_ns)
                                pipeline_audit.mark(idx, "worker_render_started_ns", worker_render_started_ns)
                                pipeline_audit.mark(idx, "worker_render_finished_ns", worker_render_finished_ns)
                                pipeline_audit.mark(idx, "shm_copy_finished_ns", shm_copy_finished_ns)
                        else:
                            idx, slot = result
                        if pipeline_audit is not None:
                            pipeline_audit.mark(idx, "future_completed_ns", future_completed_ns)
                            pipeline_audit.mark(
                                idx, "worker_done_ns",
                                pipeline_audit.frame(idx).get("shm_copy_finished_ns", future_completed_ns),
                            )
                            pipeline_audit.mark(idx, "result_observed_ns", result_observed_ns)
                        reorder_buf[idx] = slot
                        if pipeline_audit is not None:
                            pipeline_audit.sample_occupancy("in_flight", len(pending) + len(reorder_buf))

                    # Drain consecutive frames to pipe writer queue (zero-copy)
                    while next_idx in reorder_buf and not (
                        cancel_event is not None and cancel_event.is_set()
                    ):
                        slot = reorder_buf.pop(next_idx)
                        idx = next_idx
                        if pipeline_audit is not None:
                            pipeline_audit.mark(idx, "ordered_output_ns", time.perf_counter_ns())
                            pipeline_audit.mark(idx, "in_flight_at_ordered", len(pending) + len(reorder_buf) + 1)
                            pipeline_audit.mark(idx, "queue_put_started_ns", time.perf_counter_ns())
                            pipeline_audit.sample_occupancy("writer_queue", pipe_queue.qsize())
                        memview = shm_pool.get_memview(slot)
                        if pipeline_audit is not None:
                            pipeline_audit.mark(idx, "shm_view_ready_ns", time.perf_counter_ns())
                        if not _put_frame((slot, memview, idx) if pipeline_audit is not None else (slot, memview)):
                            try:
                                memview.release()
                            except Exception:
                                pass
                            shm_pool.release(slot)
                            break
                        if pipeline_audit is not None:
                            pipeline_audit.mark(idx, "queue_put_finished_ns", time.perf_counter_ns())
                        total_piped += 1
                        next_idx += 1
                        if total_piped % 50 == 0 or total_piped == total_overlay_frames:
                            _report_stream_progress(
                                total_piped, total_overlay_frames,
                                start_time, progress_cb, on_render_progress, target_fps, pipeline_audit,
                            )

                    # Aggressive top-up: fill ALL available slots in the window
                    while (
                        submitted < total_overlay_frames
                        and len(pending) + len(reorder_buf) < MAX_IN_FLIGHT
                        and not (cancel_event is not None and cancel_event.is_set())
                    ):
                        if pipeline_audit is not None:
                            pipeline_audit.frame(submitted)
                            pipeline_audit.mark(submitted, "frame_scheduled_ns", time.perf_counter_ns())
                            pipeline_audit.mark(submitted, "in_flight_at_schedule", len(pending) + len(reorder_buf))
                        slot = _acquire_shm_slot(shm_pool, process, stdout_lines, cancel_event=cancel_event)
                        pending.add(_submit_audited(submitted, slot))
                        submitted += 1

                if cancel_event is not None and cancel_event.is_set():
                    _note_cancel()
                    for f in pending:
                        f.cancel()
                    _cancel_log("producer stopped", cancel_started, process)
                    ex.shutdown(wait=False, cancel_futures=True)

                # On cancel, discard pending/reordered frames. Never encode
                # the backlog just to reach a clean queue state.
                if cancel_event is None or not cancel_event.is_set():
                    while next_idx in reorder_buf:
                        slot = reorder_buf.pop(next_idx)
                        idx = next_idx
                        if pipeline_audit is not None:
                            pipeline_audit.mark(idx, "ordered_output_ns", time.perf_counter_ns())
                            pipeline_audit.mark(idx, "in_flight_at_ordered", len(reorder_buf) + 1)
                            pipeline_audit.mark(idx, "queue_put_started_ns", time.perf_counter_ns())
                            pipeline_audit.sample_occupancy("writer_queue", pipe_queue.qsize())
                        memview = shm_pool.get_memview(slot)
                        if pipeline_audit is not None:
                            pipeline_audit.mark(idx, "shm_view_ready_ns", time.perf_counter_ns())
                        if not _put_frame((slot, memview, idx) if pipeline_audit is not None else (slot, memview)):
                            try:
                                memview.release()
                            except Exception:
                                pass
                            shm_pool.release(slot)
                            break
                        if pipeline_audit is not None:
                            pipeline_audit.mark(idx, "queue_put_finished_ns", time.perf_counter_ns())
                        total_piped += 1
                        next_idx += 1
                        _report_stream_progress(
                            total_piped, total_overlay_frames,
                            start_time, progress_cb, on_render_progress, target_fps, pipeline_audit,
                        )
                else:
                    for slot in reorder_buf.values():
                        try:
                            shm_pool.release(slot)
                        except Exception:
                            pass
                    reorder_buf.clear()
                    # Cancel: explicitly ask the writer to DROP whatever is
                    # still queued (old done_event-only semantics).  Normal EOF
                    # must never take this path (ETAP 5B tail-loss fix).
                    writer_discard_pending.set()
                    pipe_done.set()
                    _cancel_log("writer stop requested", cancel_started, process)
                    writer_t.join(timeout=1.0)
                    _cancel_log("pipe closing", cancel_started, process)
                    cancel_rc = _stop_ffmpeg_process(process, cancel_started)
                    cancel_mode = getattr(process, "_telem_cancel_mode", "forced")
                    if active_process_holder is not None:
                        active_process_holder["cancel_mode"] = cancel_mode
                        active_process_holder["cancel_rc"] = cancel_rc
                    _log_ffmpeg_tail(stdout_lines, cancel_started)
                    if cancel_mode == "graceful":
                        valid_partial = _validate_partial_mp4(output_file)
                        _cancel_log(
                            f"partial_mp4 graceful valid={valid_partial}",
                            cancel_started,
                        )
                    else:
                        _cancel_log(
                            "partial_mp4 not presented as completed export",
                            cancel_started,
                        )

        _report_phase(on_render_progress, "finalize", 0.0, "Finalizacja...", time.time() - phase_t0)

        # Signal pipe writer to finish and close stdin.
        # The sentinel is FIFO-after all frame messages, so the writer writes
        # every queued frame before it sees None.  done_event alone no longer
        # discards the backlog (ETAP 5B tail-loss fix).  join() waits until the
        # queue is really drained; the deadline is only a hang safety-net (a
        # healthy writer needs ms per frame, but FFmpeg backpressure can make
        # individual writes take seconds).
        t_drain_start = time.perf_counter()
        pipe_queue.put_nowait(None)  # sentinel (FIFO after final frames)
        pipe_done.set()
        writer_t.join(timeout=60.0)
        if writer_t.is_alive():
            print("[STREAM] WARNING: pipe writer still alive after 60s; "
                  "closing stdin anyway (possible FFmpeg backpressure hang)",
                  flush=True)
        try:
            process.stdin.close()
        except Exception:
            pass
    except BrokenPipeError:
        print("[STREAM] FFmpeg pipe closed unexpectedly.", flush=True)
    except Exception as e:
        print(f"[STREAM] Error: {e}", flush=True)
        extra = "\n".join(stdout_lines).strip()
        print(f"[STREAM] FFmpeg Output Log:\n{extra}", flush=True)
        import traceback
        traceback.print_exc()
        # Error path: discard the queued backlog like cancel does (pre-5B
        # behavior), instead of trying to write frames into a broken pipe.
        writer_discard_pending.set()
        pipe_done.set()
        try:
            pipe_queue.put_nowait(None)
        except queue.Full:
            pass
        try:
            _stop_ffmpeg_process(process, cancel_started)
        except Exception:
            pass
        raise
    finally:
        # Drain pipe_queue and release any pending memoryviews
        while not pipe_queue.empty():
            try:
                item = pipe_queue.get_nowait()
                if isinstance(item, tuple):
                    _, memview = item[:2]
                    try:
                        memview.release()
                    except Exception:
                        pass
            except Exception:
                break

        # Always clean up SHM pool
        if shm_pool is not None:
            shm_pool.close()

    stdout_t.join(timeout=2.0)
    if process.poll() is None:
        _stop_ffmpeg_process(process, cancel_started)
    t_drain_end = time.perf_counter()
    t_drain_time = t_drain_end - t_drain_start

    if active_process_holder is not None:
        active_process_holder["process"] = None

    rc = process.returncode
    if rc != 0 and not (cancel_event is not None and cancel_event.is_set()):
        extra = "\n".join(stdout_lines).strip()
        raise RuntimeError(f"FFmpeg failed with exit code {rc}\n{extra}")

    if isinstance(input_files, list) and len(input_files) > 1:
        concat_txt = Path(output_file).parent / "render_concat_list.txt"
        if concat_txt.exists():
            concat_txt.unlink()

    t_postprocess_start = time.perf_counter()
    if nv_rot180_cuda:
        # The local FFmpeg drops the display-matrix through overlay_cuda and
        # cannot write one via -metadata/-display_rotation, so inject the
        # rotation=180 display matrix into the video track's tkhd and verify it.
        # Raises on failure so the export is never reported as successful with a
        # physically-rotated file that is missing the rotation metadata.
        _inject_rot180_displaymatrix(output_file, render_w, render_h)
    t_postprocess_end = time.perf_counter()
    t_postprocess_time = t_postprocess_end - t_postprocess_start

    t_prod_end = t_postprocess_end
    t_prod_total = t_prod_end - t_prod_start
    t_prep_time = t_prep_end - t_prep_start
    t_worker_init_time = t_worker_init_pre_end - t_worker_init_start
    t_ffmpeg_startup_time = t_ffmpeg_started - t_ffmpeg_start
    first_frame_lat = (writer_stats["first_frame_time"] - t_prod_start) if writer_stats["first_frame_time"] is not None else 0.0
    frame_pipeline_time = (writer_stats["last_frame_time"] - writer_stats["first_frame_time"]) if (writer_stats["first_frame_time"] and writer_stats["last_frame_time"]) else (t_drain_start - t_ffmpeg_started)
    pipeline_fps = (total_overlay_frames / frame_pipeline_time) if frame_pipeline_time > 0 else 0.0
    real_export_fps = (total_overlay_frames / t_prod_total) if t_prod_total > 0 else 0.0
    total_overhead = max(0.0, t_prod_total - frame_pipeline_time)
    overhead_pct = (total_overhead / t_prod_total * 100.0) if t_prod_total > 0 else 0.0

    # Wydrukuj podsumowanie wydajności renderowania
    BenchmarkTracker.get_instance().print_summary()

    if encoder == "nv":
        summary = BenchmarkTracker.get_instance().get_summary()
        write_stats = summary.get("ffmpeg_write", {"avg": 0.0, "p95": 0.0})
        write_avg = write_stats.get("avg", 0.0)
        write_p95 = write_stats.get("p95", 0.0)

        print("\n=== NVIDIA PRODUCTION EXPORT TIMING ===", flush=True)
        print(f"\nFrames                 : {total_overlay_frames}", flush=True)
        print(f"\nPREPARE                 : {t_prep_time:.3f} s", flush=True)
        print(f"WORKER_INIT             : {t_worker_init_time:.3f} s", flush=True)
        print(f"FFMPEG_STARTUP          : {t_ffmpeg_startup_time:.3f} s", flush=True)
        print(f"FIRST_FRAME_LATENCY     : {first_frame_lat:.3f} s", flush=True)
        print(f"FRAME_PIPELINE          : {frame_pipeline_time:.3f} s", flush=True)
        print(f"FFMPEG_DRAIN_FINALIZE   : {t_drain_time:.3f} s", flush=True)
        print(f"POSTPROCESS             : {t_postprocess_time:.3f} s", flush=True)
        print(f"\nPRODUCTION_TOTAL        : {t_prod_total:.3f} s", flush=True)
        print(f"\nPIPELINE_FPS            : {pipeline_fps:.1f}", flush=True)
        print(f"REAL_EXPORT_FPS         : {real_export_fps:.1f}", flush=True)
        print(f"\nTOTAL_OVERHEAD          : {total_overhead:.3f} s", flush=True)
        print(f"OVERHEAD                : {overhead_pct:.1f} %", flush=True)
        print(f"\nffmpeg_write avg        : {write_avg:.2f} ms", flush=True)
        print(f"ffmpeg_write p95        : {write_p95:.2f} ms\n", flush=True)

    if pipeline_audit is not None:
        audit_result = pipeline_audit.finalize({
            "encoder": encoder,
            "frames": total_overlay_frames,
            "workers": n_workers,
            "max_in_flight": MAX_IN_FLIGHT,
            "shm_slots": n_shm_slots,
            "frame_size_bytes": frame_size,
            "stream_size": [stream_w, stream_h],
            "overlay_size": [overlay_w, overlay_h],
            "preview": bool(on_render_progress),
            "hud_mode": "DIRECT_REGION" if hud_regions is not None else ("SINGLE_BBOX" if hud_bbox is not None else "FULL_FRAME"),
            "pipeline_fps": pipeline_fps,
            "real_export_fps": real_export_fps,
            "writer": {
                "mode": "buffered",
                "stream_type": writer_stats.get("stream_type"),
                "stream_module": writer_stats.get("stream_module"),
                "frames_written": writer_stats.get("frames_written", 0),
                "requested_bytes": writer_stats.get("requested_bytes", 0),
                "returned_bytes": writer_stats.get("returned_bytes", 0),
                "write_calls": writer_stats.get("write_calls", 0),
                "partial_write_frames": writer_stats.get("partial_write_frames", 0),
                "idle_wait_ms": writer_stats.get("idle_wait_ns", 0) / 1_000_000.0,
                "busy_write_ms": writer_stats.get("busy_write_ns", 0) / 1_000_000.0,
                "thread_active_ms": (
                    (writer_stats.get("thread_finished_ns", 0) - writer_stats.get("thread_started_ns", 0)) / 1_000_000.0
                    if writer_stats.get("thread_finished_ns") and writer_stats.get("thread_started_ns") else 0.0
                ),
                "idle_percent": (
                    writer_stats.get("idle_wait_ns", 0)
                    / max(1, writer_stats.get("thread_finished_ns", 0) - writer_stats.get("thread_started_ns", 0))
                    * 100.0
                    if writer_stats.get("thread_finished_ns") and writer_stats.get("thread_started_ns") else 0.0
                ),
                "busy_write_percent": (
                    writer_stats.get("busy_write_ns", 0)
                    / max(1, writer_stats.get("thread_finished_ns", 0) - writer_stats.get("thread_started_ns", 0))
                    * 100.0
                    if writer_stats.get("thread_finished_ns") and writer_stats.get("thread_started_ns") else 0.0
                ),
            },
        })
        print(
            f"[5F AUDIT] lifecycle={audit_result['artifacts']['json']} "
            f"csv={audit_result['artifacts']['csv']}", flush=True,
        )

    return total_piped


def _inject_rot180_displaymatrix(
    output_file: str,
    render_w: int,
    render_h: int,
) -> bool:
    """Inject and verify the rotation=180 display matrix into the output MP4.

    Runs only in NVIDIA ROT180 CUDA mode (the caller guards with nv_rot180_cuda).
    Raises RuntimeError if the displaymatrix cannot be written or verified, so the
    export is reported as an error instead of silently producing a physically
    rotated file marked as done.
    """
    try:
        from src.ffmpeg.displaymatrix import write_rotation_180_displaymatrix

        ok = write_rotation_180_displaymatrix(output_file, render_w, render_h)
        if not ok:
            raise RuntimeError(
                "displaymatrix rotate=180 could not be written/verified "
                "(unexpected MP4 structure)"
            )
        print("[NVIDIA] displaymatrix rotate=180 injected and verified", flush=True)
        return True
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"displaymatrix rotate=180 injection failed: {e}") from e
