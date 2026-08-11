"""FFmpeg piping and streaming logic.

Manages writing frames into the FFmpeg stdin pipe asynchronously using writer threads,
handles process lifetime, and reports progress.
"""

from __future__ import annotations

import math
import os
import queue
import subprocess
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from src.ffmpeg.detection import detect_gpu_decoder
from src.ffmpeg.worker_cache import init_worker
from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd
from src.ffmpeg.shared_memory import (
    SharedFramePool,
    _init_worker_with_shm,
    render_frame_shm_job,
)
from src.ffmpeg.frame_renderer import render_frame_bytes_job
from src.benchmark import BenchmarkTracker


def _pipe_writer_thread(
    write_queue: queue.Queue,
    stdin_buffer: Any,
    done_event: threading.Event,
) -> None:
    """Background thread that drains frame bytes to FFmpeg stdin pipe.

    Receives (bytes_data,) from write_queue and writes to stdin_buffer.
    Terminates when done_event is set and queue is empty, or on None sentinel.
    """
    bt = BenchmarkTracker.get_instance()
    try:
        while True:
            try:
                item = write_queue.get(timeout=0.5)
            except queue.Empty:
                if done_event.is_set():
                    break
                continue
            if item is None:  # sentinel
                break
            bt.start_timer("ffmpeg_write")
            try:
                stdin_buffer.write(item)
            finally:
                bt.stop_timer("ffmpeg_write")
    except (BrokenPipeError, OSError):
        pass


def _report_stream_progress(
    done: int, total: int, start_time: float, progress_cb: Optional[Callable]
) -> None:
    """Report streaming progress."""
    elapsed = time.time() - start_time
    m, s = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    fps = done / elapsed if elapsed > 0 else 0
    stats = f"Stream: {done}/{total} | fps: {fps:.1f} | elapse: {h:02d}:{m:02d}:{s:02d}"
    if progress_cb:
        progress_cb(done, stats)


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
            try:
                process.terminate()
            except Exception:
                pass
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
    process.wait()
    rc = process.returncode
    if rc != 0:
        extra = "\n".join(other_output).strip()
        raise RuntimeError(f"FFmpeg process failed with exit code {rc}\n{extra}")
    if active_process_holder is not None:
        active_process_holder["process"] = None


def stream_overlay_to_ffmpeg(
    ffmpeg_exe: str,
    input_files: list,
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
    target_fps: float = 30.0,
    update_rate_step: int = 1,
    max_distance_m: Optional[float] = None,
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
    progress_cb: Optional[Callable] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
    encoder: str = "nv",
    gpu: int = 0,
    resolution_name: str = "source",
    video_bitrate: str = "",
    rotation_degrees: int = 0,
    container_rotation: int = 0,
    overlay_w: int = 1920,
    overlay_h: int = 1080,
    render_w: int = 1920,
    render_h: int = 1080,
) -> int:
    """
    Producer-Consumer pipeline:
    - Producer: ProcessPoolExecutor renders frames in parallel -> (index, bytes)
    - Consumer: main thread receives, sorts by index, pipes to FFmpeg
    """
    # Pobierz cut_regions z layoutu (przekazane przez kontroler)
    cut_regions = layout.get("cut_regions", [])

    generation_fps = target_fps / update_rate_step
    total_overlay_frames = max(1, math.ceil(duration_s * generation_fps))

    effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees
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
    )

    if cancel_event is not None and cancel_event.is_set():
        return 0

    # Build FFmpeg input args
    hwaccel = detect_gpu_decoder(encoder)
    input_args: list[str] = []
    audio_input_args: list[str] = []
    if hwaccel:
        input_args.extend(["-hwaccel", hwaccel])
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
        auto_rot = "-noautorotate" if container_rotation != 0 else "-autorotate"
        input_args.extend([auto_rot, "-i", str(input_file)])
        audio_input_args.extend(["-i", str(input_file)])

    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe, input_args, output_file,
        overlay_w, overlay_h, generation_fps,
        encoder, gpu, video_bitrate,
        render_w, render_h, resolution_name,
        container_rotation, rotation_degrees,
        hwaccel=hwaccel,
        cut_regions=cut_regions,
        audio_input_args=audio_input_args,
    )

    print("FFmpeg streaming cmd:", " ".join(map(str, cmd)), flush=True)
    print(
        f"[STREAM] overlay={overlay_w}x{overlay_h}  render={render_w}x{render_h}  "
        f"gen_fps={generation_fps}  frames={total_overlay_frames}",
        flush=True,
    )
    print(f"[STREAM] filter: {filter_complex}", flush=True)

    # Start FFmpeg
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

    start_time = time.time()
    total_piped = 0
    workers = workers or max(1, (os.cpu_count() or 1) - 1)
    n_workers = min(workers, total_overlay_frames)

    # Frame size in bytes: RGBA = 4 bytes per pixel
    frame_size = overlay_w * overlay_h * 4

    shm_pool: SharedFramePool | None = None
    if n_workers > 1:
        # Number of SHM slots: enough to keep workers busy + reorder buffer
        MAX_IN_FLIGHT = max(4, n_workers * 2)
        n_shm_slots = MAX_IN_FLIGHT
        shm_pool = SharedFramePool(n_shm_slots, frame_size)
    else:
        MAX_IN_FLIGHT = 1
        n_shm_slots = 1

    # ── Async pipe writer (background thread) ───────────────────────────
    pipe_queue: queue.Queue = queue.Queue(maxsize=max(8, n_workers * 2))
    pipe_done = threading.Event()
    writer_t = threading.Thread(
        target=_pipe_writer_thread,
        args=(pipe_queue, process.stdin.buffer, pipe_done, shm_pool),
        daemon=True,
    )
    writer_t.start()

    try:
        if n_workers <= 1:
            # Single worker — no IPC, direct rendering
            for i in range(total_overlay_frames):
                if cancel_event is not None and cancel_event.is_set():
                    break
                _, raw_bytes = render_frame_bytes_job((i,))
                pipe_queue.put(raw_bytes)
                total_piped += 1
                if total_piped % 50 == 0 or total_piped == total_overlay_frames:
                    _report_stream_progress(total_piped, total_overlay_frames, start_time, progress_cb)
        else:
            from concurrent.futures import wait, FIRST_COMPLETED

            shm_names = shm_pool.shm_names()

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
                cut_regions, effective_rotation,
            )

            print(
                f"[STREAM] SHM pool: {n_shm_slots} slots × {frame_size / 1024 / 1024:.1f} MB = "
                f"{n_shm_slots * frame_size / 1024 / 1024:.0f} MB total | "
                f"workers={n_workers} | MAX_IN_FLIGHT={MAX_IN_FLIGHT}",
                flush=True,
            )

            with ProcessPoolExecutor(
                max_workers=n_workers,
                initializer=_init_worker_with_shm,
                initargs=(shm_names, frame_size, *init_args),
            ) as ex:
                pending: set = set()
                reorder_buf: dict[int, int] = {}  # frame_idx -> shm_slot
                next_idx = 0
                submitted = 0

                # Fill initial window — acquire SHM slots and submit jobs
                for _ in range(min(MAX_IN_FLIGHT, total_overlay_frames)):
                    slot = shm_pool.acquire(timeout=30.0)
                    pending.add(ex.submit(render_frame_shm_job, (submitted, slot)))
                    submitted += 1

                while pending and not (
                    cancel_event is not None and cancel_event.is_set()
                ):
                    done, pending = wait(pending, return_when=FIRST_COMPLETED,
                                         timeout=0.1)
                    for fut in done:
                        idx, slot = fut.result()
                        reorder_buf[idx] = slot

                    # Drain consecutive frames to pipe writer queue (zero-copy)
                    while next_idx in reorder_buf:
                        slot = reorder_buf.pop(next_idx)
                        memview = shm_pool.get_memview(slot)
                        pipe_queue.put((slot, memview))
                        total_piped += 1
                        next_idx += 1
                        if total_piped % 50 == 0 or total_piped == total_overlay_frames:
                            _report_stream_progress(
                                total_piped, total_overlay_frames,
                                start_time, progress_cb,
                            )

                    # Aggressive top-up: fill ALL available slots in the window
                    while (
                        submitted < total_overlay_frames
                        and len(pending) + len(reorder_buf) < MAX_IN_FLIGHT
                    ):
                        slot = shm_pool.acquire(timeout=30.0)
                        pending.add(
                            ex.submit(render_frame_shm_job, (submitted, slot))
                        )
                        submitted += 1

                if cancel_event is not None and cancel_event.is_set():
                    for f in pending:
                        f.cancel()
                    ex.shutdown(wait=False, cancel_futures=True)

                # Drain final reorder buffer (zero-copy)
                while next_idx in reorder_buf:
                    slot = reorder_buf.pop(next_idx)
                    memview = shm_pool.get_memview(slot)
                    pipe_queue.put((slot, memview))
                    total_piped += 1
                    next_idx += 1
                    _report_stream_progress(
                        total_piped, total_overlay_frames,
                        start_time, progress_cb,
                    )

        # Signal pipe writer to finish and close stdin
        pipe_done.set()
        pipe_queue.put(None)  # sentinel
        writer_t.join(timeout=30.0)
        try:
            process.stdin.close()
        except Exception:
            pass
    except BrokenPipeError:
        print("[STREAM] FFmpeg pipe closed unexpectedly.", flush=True)
    except Exception as e:
        print(f"[STREAM] Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        pipe_done.set()
        pipe_queue.put(None)
        try:
            process.terminate()
        except Exception:
            pass
        raise
    finally:
        # Always clean up SHM pool
        if shm_pool is not None:
            shm_pool.close()

    stdout_t.join(timeout=10.0)
    process.wait()

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

    # Wydrukuj podsumowanie wydajności renderowania
    BenchmarkTracker.get_instance().print_summary()

    return total_piped
