"""Finalization phase tracker, profiler, and background monitor for TeleM.

Tracks distinct finalization stages (drain, encoder close, MP4 mux, postprocess),
samples output file growth and rolling MB/s, calculates queue drain progress,
detects I/O stalls, and logs structured timing metrics.
"""
from __future__ import annotations

import collections
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional


class FinalizationTracker:
    """Thread-safe monitor and profiler for export finalization."""

    # Explicit stage names matching UX specifications
    STAGE_DRAIN = "Finalizacja: opróżnianie klatek"
    STAGE_ENCODER = "Finalizacja: zamykanie enkodera"
    STAGE_MUX = "Finalizacja: zapis MP4"
    STAGE_POSTPROCESS = "Finalizacja: postprocess"

    def __init__(
        self,
        output_paths: list[str | Path] | str | Path = (),
        *,
        on_progress: Optional[Callable] = None,
        cancel_event: Optional[threading.Event] = None,
        active_process_holder: Optional[dict[str, Any]] = None,
        sample_interval_s: float = 0.5,
        poll_interval_s: Optional[float] = None,
        stall_threshold_s: float = 10.0,
    ) -> None:
        if poll_interval_s is not None:
            sample_interval_s = poll_interval_s
        
        if isinstance(output_paths, (str, Path)):
            self._target_paths = [Path(output_paths)]
        else:
            self._target_paths = [Path(p) for p in output_paths]

        self._on_progress = on_progress
        self._cancel_event = cancel_event
        self._active_process_holder = active_process_holder
        self._sample_interval_s = max(0.01, float(sample_interval_s))
        self._stall_threshold_s = max(0.05, float(stall_threshold_s))

        # Thread synchronization
        self._lock = threading.RLock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None

        # Timing milestones
        self.t_start = time.perf_counter()
        self.t_queue_drain_start: Optional[float] = None
        self.t_queue_drain_end: Optional[float] = None
        self.t_writer_join_start: Optional[float] = None
        self.t_writer_join_end: Optional[float] = None
        self.t_stdin_close_start: Optional[float] = None
        self.t_stdin_close_end: Optional[float] = None
        self.t_ffmpeg_wait_start: Optional[float] = None
        self.t_ffmpeg_wait_end: Optional[float] = None
        self.t_postprocess_start: Optional[float] = None
        self.t_postprocess_end: Optional[float] = None
        self.t_end: Optional[float] = None

        # Queue / drain diagnostics
        self.queued_at_start: int = 0
        self.writer_frames_pending: int = 0
        self.writer_frames_completed: int = 0
        self.initial_drain_backlog: int = 0

        # File growth & I/O tracking
        self.output_size_at_start = self._sample_max_file_size()
        self.output_size_at_end = 0
        self._size_samples: collections.deque[tuple[float, int]] = collections.deque()
        if self.output_size_at_start >= 0:
            self._size_samples.append((time.perf_counter(), self.output_size_at_start))

        self.last_progress_time = time.perf_counter()
        self.last_known_size = max(0, self.output_size_at_start)
        self.last_known_frames_written = 0

        # Current state
        self._stage = self.STAGE_DRAIN
        self._drain_pct: Optional[float] = None
        self._rolling_mbps: float = 0.0
        self._stall_warning = False
        self._stall_seconds = 0
        self._last_emit_time = 0.0
        self._last_log_time = 0.0

    def add_target_path(self, path: str | Path) -> None:
        """Add additional candidate output path (e.g. .temp_video.mp4 or .part)."""
        p = Path(path)
        with self._lock:
            if p not in self._target_paths:
                self._target_paths.append(p)

    def _sample_max_file_size(self) -> int:
        """Query maximum size among target file candidates without crashing."""
        max_size = 0
        found = False
        with self._lock:
            paths = list(self._target_paths)
        for p in paths:
            try:
                if p.exists():
                    s = p.stat().st_size
                    if s > max_size:
                        max_size = s
                    found = True
            except (OSError, PermissionError):
                pass
        return max_size if found else 0

    def start(self) -> None:
        """Start background sampling thread and print initial log header."""
        self._running = True
        self.t_start = time.perf_counter()
        self.output_size_at_start = self._sample_max_file_size()
        self.last_known_size = self.output_size_at_start
        self.last_progress_time = self.t_start
        self._size_samples.clear()
        self._size_samples.append((self.t_start, self.output_size_at_start))

        print("\n[Finalize] START", flush=True)

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="FinalizationMonitor",
            daemon=True,
        )
        self._monitor_thread.start()
        self._emit_progress(force=True)

    def stop(self) -> None:
        """Stop background sampling thread and finalize timings."""
        self._running = False
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)
        self.t_end = time.perf_counter()
        self.output_size_at_end = self._sample_max_file_size()

    def set_stage(
        self,
        stage: str,
        *,
        queue_size: Optional[int] = None,
        frames_written: Optional[int] = None,
        total_frames: Optional[int] = None,
    ) -> None:
        """Transition to a new finalization stage with optional queue stats."""
        with self._lock:
            self._stage = stage
            if queue_size is not None:
                self.writer_frames_pending = max(0, queue_size)
            if frames_written is not None:
                self.writer_frames_completed = max(0, frames_written)
                if self.writer_frames_completed > self.last_known_frames_written:
                    self.last_known_frames_written = self.writer_frames_completed
                    self.last_progress_time = time.perf_counter()
                    self._stall_warning = False

            if total_frames is not None and frames_written is not None:
                if self.initial_drain_backlog <= 0:
                    self.initial_drain_backlog = max(1, total_frames - frames_written)
                progress_in_drain = max(0, frames_written - (total_frames - self.initial_drain_backlog))
                self._drain_pct = min(100.0, (progress_in_drain / self.initial_drain_backlog) * 100.0)

        self._emit_progress(force=True)

    def mark_drain_start(self, queued_count: int, frames_written: int = 0, total_frames: int = 0) -> None:
        self.t_queue_drain_start = time.perf_counter()
        self.queued_at_start = max(0, queued_count)
        self.writer_frames_pending = self.queued_at_start
        self.writer_frames_completed = frames_written
        if total_frames > frames_written:
            self.initial_drain_backlog = max(1, total_frames - frames_written)
        else:
            self.initial_drain_backlog = max(1, self.queued_at_start)
        self.set_stage(self.STAGE_DRAIN, queue_size=queued_count, frames_written=frames_written, total_frames=total_frames)

    def mark_writer_done(self) -> None:
        now = time.perf_counter()
        self.t_queue_drain_end = now
        self.t_writer_join_end = now
        drain_ms = (now - self.t_queue_drain_start) * 1000.0 if self.t_queue_drain_start else 0.0
        print(
            f"[Finalize] writer_done: queue_drain_ms={drain_ms:.2f} "
            f"queued_at_start={self.queued_at_start} "
            f"writer_frames_completed={self.writer_frames_completed}",
            flush=True,
        )

    def mark_stdin_closed(self) -> None:
        self.t_stdin_close_end = time.perf_counter()
        print(f"[Finalize] stdin_closed ts_epoch={time.time():.6f}", flush=True)

    def mark_ffmpeg_wait_start(self) -> None:
        self.t_ffmpeg_wait_start = time.perf_counter()
        proc_alive = None
        if self._active_process_holder is not None:
            proc = self._active_process_holder.get("process")
            proc_alive = proc is not None and proc.poll() is None
        print(
            f"[Finalize] ffmpeg_wait_start ts_epoch={time.time():.6f} "
            f"ffmpeg_alive={proc_alive}",
            flush=True,
        )
        self.set_stage(self.STAGE_MUX)

    def mark_ffmpeg_wait_end(self) -> None:
        self.t_ffmpeg_wait_end = time.perf_counter()
        wait_ms = (self.t_ffmpeg_wait_end - self.t_ffmpeg_wait_start) * 1000.0 if self.t_ffmpeg_wait_start else 0.0
        print(
            f"[Finalize] ffmpeg_wait_done: wait_ms={wait_ms:.2f} "
            f"ts_epoch={time.time():.6f}",
            flush=True,
        )

    def mark_postprocess_start(self) -> None:
        self.t_postprocess_start = time.perf_counter()
        self.set_stage(self.STAGE_POSTPROCESS)

    def mark_postprocess_end(self) -> None:
        self.t_postprocess_end = time.perf_counter()
        post_ms = (self.t_postprocess_end - self.t_postprocess_start) * 1000.0 if self.t_postprocess_start else 0.0
        print(f"[Finalize] postprocess_done: postprocess_ms={post_ms:.2f}", flush=True)

    def update_queue_status(self, pending: int, written: int, total_frames: int) -> None:
        """Periodically update writer queue backlog for real drain %."""
        with self._lock:
            self.writer_frames_pending = max(0, pending)
            self.writer_frames_completed = max(0, written)
            if self.writer_frames_completed > self.last_known_frames_written:
                self.last_known_frames_written = self.writer_frames_completed
                self.last_progress_time = time.perf_counter()
                self._stall_warning = False

            if self.initial_drain_backlog > 0:
                drain_done = max(0, self.initial_drain_backlog - self.writer_frames_pending)
                self._drain_pct = min(100.0, (drain_done / self.initial_drain_backlog) * 100.0)

    @property
    def stage(self) -> str:
        with self._lock:
            return self._stage

    @property
    def queue_pending(self) -> int:
        with self._lock:
            return self.writer_frames_pending

    def _process_sample(self, now: float, current_size: int) -> None:
        with self._lock:
            # Append sample to rolling deque (keep last 3.5 seconds)
            self._size_samples.append((now, current_size))
            while self._size_samples and now - self._size_samples[0][0] > 3.5:
                self._size_samples.popleft()

            # Calculate rolling MB/s
            if len(self._size_samples) >= 2:
                dt = self._size_samples[-1][0] - self._size_samples[0][0]
                d_bytes = self._size_samples[-1][1] - self._size_samples[0][1]
                if dt >= 0.08 and d_bytes >= 0:
                    self._rolling_mbps = (d_bytes / (1024.0 * 1024.0)) / dt
                elif dt >= 0.08:
                    self._rolling_mbps = 0.0

            # Detect progress
            if current_size > self.last_known_size + 65536:
                self.last_known_size = current_size
                self.last_progress_time = now
                self._stall_warning = False

            stall_dt = now - self.last_progress_time
            if stall_dt >= self._stall_threshold_s:
                # Verify FFmpeg process is alive
                proc_alive = True
                if self._active_process_holder is not None:
                    proc = self._active_process_holder.get("process")
                    if proc is not None and proc.poll() is not None:
                        proc_alive = False
                if proc_alive:
                    self._stall_warning = True
                    self._stall_seconds = int(stall_dt)

    def sample_now(self) -> None:
        """Perform one immediate sampling tick (useful synchronously or in tests)."""
        now = time.perf_counter()
        current_size = self._sample_max_file_size()
        self._process_sample(now, current_size)

    def _monitor_loop(self) -> None:
        """Background sampling loop for file size, MB/s, and stall detection."""
        while self._running:
            if self._cancel_event is not None and self._cancel_event.is_set():
                break

            now = time.perf_counter()
            current_size = self._sample_max_file_size()
            self._process_sample(now, current_size)

            # Log periodic status (~1 Hz)
            if now - self._last_log_time >= 1.0:
                self._last_log_time = now
                elapsed_s = now - self.t_start
                size_mb = current_size / (1024.0 * 1024.0)
                if self._stage == self.STAGE_MUX:
                    print(
                        f"[Finalize] ffmpeg_wait elapsed={elapsed_s:.1f}s "
                        f"output_size={size_mb / 1024.0:.2f}GB growth_MBps={self._rolling_mbps:.1f}",
                        flush=True,
                    )
                elif self._stage == self.STAGE_DRAIN:
                    drain_txt = f"{self._drain_pct:.0f}%" if self._drain_pct is not None else "--"
                    print(
                        f"[Finalize] drain elapsed={elapsed_s:.1f}s "
                        f"drain_pct={drain_txt} pending={self.writer_frames_pending}",
                        flush=True,
                    )

            self._emit_progress()
            time.sleep(self._sample_interval_s)

    def _emit_progress(self, force: bool = False) -> None:
        """Emit GUI progress milestone."""
        if self._on_progress is None:
            return

        now = time.perf_counter()
        if not force and now - self._last_emit_time < 0.2:
            return
        self._last_emit_time = now

        with self._lock:
            stage = self._stage
            drain_pct = self._drain_pct
            mbps = self._rolling_mbps
            size_bytes = self._sample_max_file_size()
            stall_warn = self._stall_warning
            stall_sec = self._stall_seconds
            t_elapsed = now - self.t_start

        # Format label cleanly for display
        if stall_warn:
            label = f"Finalizacja trwa — brak postępu zapisu od {stall_sec} s"
        elif stage == self.STAGE_DRAIN:
            if drain_pct is not None:
                label = f"Finalizacja: opróżnianie klatek {drain_pct:.0f}%"
            else:
                label = "Finalizacja: opróżnianie klatek"
        elif stage == self.STAGE_ENCODER:
            label = "Finalizacja: zamykanie enkodera"
        elif stage == self.STAGE_MUX:
            label = "Finalizacja: zapis MP4"
        elif stage == self.STAGE_POSTPROCESS:
            label = "Finalizacja: postprocess"
        else:
            label = stage

        # Map to internal percentage for progress tracker
        if stage == self.STAGE_DRAIN:
            internal = (drain_pct / 100.0) if drain_pct is not None else 0.5
        elif stage == self.STAGE_ENCODER:
            internal = 0.6
        elif stage == self.STAGE_MUX:
            internal = 0.8
        elif stage == self.STAGE_POSTPROCESS:
            internal = 0.95
        else:
            internal = 0.5

        state = {
            "phase": "finalize",
            "pct": internal,
            "label": label,
            "finalize_stage": stage,
            "finalize_time_s": t_elapsed,
            "file_size_bytes": size_bytes,
            "write_speed_mbps": mbps,
            "drain_pct": drain_pct,
            "stall_warning": stall_warn,
            "stall_seconds": stall_sec,
        }

        try:
            self._on_progress(0, 0, t_elapsed, 0.0, state)
        except Exception:
            pass

    def current_stage_label(self) -> str:
        """User-facing stage description for display."""
        with self._lock:
            stage = self._stage
            drain_pct = self._drain_pct
            stall_warn = self._stall_warning
            stall_sec = self._stall_seconds
        if stall_warn:
            return f"Finalizacja trwa — brak postępu zapisu od {stall_sec} s"
        elif stage == self.STAGE_DRAIN:
            if drain_pct is not None:
                return f"Finalizacja: opróżnianie klatek {drain_pct:.0f}%"
            return "Finalizacja: opróżnianie klatek"
        elif stage == self.STAGE_ENCODER:
            return "Finalizacja: zamykanie enkodera"
        elif stage == self.STAGE_MUX:
            return "Finalizacja: zapis MP4 / mux"
        elif stage == self.STAGE_POSTPROCESS:
            return "Finalizacja: postprocess"
        return stage

    def format_gui_status(self) -> str:
        """Format a rich status line for GUI header."""
        with self._lock:
            stage = self._stage
            drain_pct = self._drain_pct
            mbps = self._rolling_mbps
            size_bytes = self._sample_max_file_size()
            stall_warn = self._stall_warning
            stall_sec = self._stall_seconds
            t_elapsed = time.perf_counter() - self.t_start

        mins, secs = divmod(int(t_elapsed), 60)
        t_str = f"{mins:02d}:{secs:02d}"
        size_gb = size_bytes / (1024.0 * 1024.0 * 1024.0)

        if stall_warn:
            return f"Finalizacja: brak przyrostu pliku od {stall_sec}s (oczekiwanie na dysk) | {t_str}"
        elif stage == self.STAGE_DRAIN:
            if drain_pct is not None:
                return f"Finalizacja: opróżnianie klatek {drain_pct:.0f}% | {t_str}"
            return f"Finalizacja: opróżnianie klatek | {t_str}"
        elif stage == self.STAGE_ENCODER:
            return f"Finalizacja: zamykanie enkodera | {t_str}"
        elif stage == self.STAGE_MUX:
            rate_str = f" | {mbps:.1f} MB/s" if mbps > 0.05 else ""
            return f"Finalizacja: zapis MP4 | {size_gb:.2f} GB{rate_str} | {t_str}"
        elif stage == self.STAGE_POSTPROCESS:
            return f"Finalizacja: postprocess | {t_str}"
        return f"Finalizacja | {t_str}"

    class StateSnapshot:
        def __init__(self, stage: str, bytes_written: int, rolling_mb_s: float, is_stalled: bool, stall_sec: int, current_bytes: int = 0):
            self.stage = stage
            self.bytes_written = bytes_written
            self.rolling_mb_s = rolling_mb_s
            self.is_stalled = is_stalled
            self.stall_sec = stall_sec
            self.current_bytes = current_bytes

    def get_state(self) -> StateSnapshot:
        with self._lock:
            current_size = self._sample_max_file_size()
            bytes_written = max(0, current_size - self.output_size_at_start)
            return self.StateSnapshot(
                stage=self._stage,
                bytes_written=bytes_written,
                rolling_mb_s=self._rolling_mbps,
                is_stalled=self._stall_warning,
                stall_sec=self._stall_seconds,
                current_bytes=current_size,
            )

    def get_timings(self) -> dict[str, Any]:
        return self.get_summary()

    def get_summary(self) -> dict[str, Any]:
        """Compile complete profiling summary."""
        now = self.t_end or time.perf_counter()
        drain_ms = ((self.t_queue_drain_end or now) - (self.t_queue_drain_start or self.t_start)) * 1000.0 if self.t_queue_drain_start else 0.0
        stdin_ms = ((self.t_stdin_close_end or now) - (self.t_stdin_close_start or self.t_start)) * 1000.0 if self.t_stdin_close_start else 0.0
        ffmpeg_wait_ms = ((self.t_ffmpeg_wait_end or now) - (self.t_ffmpeg_wait_start or self.t_start)) * 1000.0 if self.t_ffmpeg_wait_start else 0.0
        post_ms = ((self.t_postprocess_end or now) - (self.t_postprocess_start or self.t_start)) * 1000.0 if self.t_postprocess_start else 0.0
        total_ms = (now - self.t_start) * 1000.0

        bytes_written = max(0, self.output_size_at_end - self.output_size_at_start)

        return {
            "finalize_start": self.t_start,
            "queue_drain_ms": drain_ms,
            "writer_join_ms": drain_ms,
            "stdin_close_ms": stdin_ms,
            "ffmpeg_exit_wait_ms": ffmpeg_wait_ms,
            "postprocess_ms": post_ms,
            "finalize_total_ms": total_ms,
            "output_file_size_at_finalize_start": self.output_size_at_start,
            "output_file_size_at_finalize_end": self.output_size_at_end,
            "bytes_written_during_finalize": bytes_written,
            "rolling_write_mbps": self._rolling_mbps,
            "queued_at_finalize_start": self.queued_at_start,
            "writer_frames_pending": self.writer_frames_pending,
            "writer_frames_completed": self.writer_frames_completed,
        }

    def print_summary(self) -> None:
        """Print final structured log block conforming to Section 16."""
        s = self.get_summary()
        print("\n=== FINALIZATION PROFILING SUMMARY ===", flush=True)
        print(f"[Finalize] queue_drain_ms:       {s['queue_drain_ms']:.2f} ms", flush=True)
        print(f"[Finalize] stdin_close_ms:       {s['stdin_close_ms']:.2f} ms", flush=True)
        print(f"[Finalize] ffmpeg_exit_wait_ms:  {s['ffmpeg_exit_wait_ms']:.2f} ms", flush=True)
        print(f"[Finalize] postprocess_ms:       {s['postprocess_ms']:.2f} ms", flush=True)
        print(f"[Finalize] output_size_start:    {s['output_file_size_at_finalize_start']} bytes", flush=True)
        print(f"[Finalize] output_size_end:      {s['output_file_size_at_finalize_end']} bytes", flush=True)
        print(f"[Finalize] bytes_written:        {s['bytes_written_during_finalize']} bytes", flush=True)
        print(f"[Finalize] finalize_total_ms:    {s['finalize_total_ms']:.2f} ms", flush=True)
        print("[Finalize] DONE\n", flush=True)
