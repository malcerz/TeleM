"""Low-cost liveness diagnostics for the AMD native render path only."""
from __future__ import annotations

import faulthandler
import json
import queue
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional


NATIVE_STAGE_NAMES = {
    0: "idle",
    1: "decode_wait",
    2: "decoded",
    3: "vp_compose",
    4: "amf_query",
    5: "amf_submit",
    6: "packet_write",
    7: "frame_complete",
    8: "flush",
}


class NonBlockingProgressDispatcher:
    """Keep GUI callbacks out of the frame-processing dependency chain."""

    def __init__(self, *, capacity: int = 32) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=max(2, capacity))
        self._stop = threading.Event()
        self.errors: list[BaseException] = []
        self.thread = threading.Thread(
            target=self._run, name="TeleM-AMD-Progress", daemon=True
        )
        self.thread.start()

    def submit(self, callback: Optional[Callable], *args: Any) -> None:
        if callback is None or self._stop.is_set():
            return
        item = (callback, args)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Progress is state, not an event log.  Dropping the oldest stale
            # snapshot keeps rendering independent from a blocked GUI thread.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                pass

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                callback, args = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                callback(*args)
            except BaseException as exc:  # callback failure must not kill render
                self.errors.append(exc)
                print(f"[AMD PROGRESS] callback failed: {exc}", flush=True)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self.thread.join(timeout=max(0.0, timeout))
        if self.thread.is_alive():
            print("[AMD PROGRESS] callback thread still busy; render shutdown continues.", flush=True)


class AMDRenderWatchdog:
    """Emit periodic pipeline snapshots and a one-shot freeze thread dump."""

    def __init__(
        self,
        snapshot: Callable[[], dict[str, Any]],
        *,
        cancel_event: Optional[Any],
        dump_path: str | Path,
        diagnostic_path: str | Path | None = None,
        heartbeat_s: float = 5.0,
        warn_s: float = 2.0,
        detail_s: float = 5.0,
        freeze_s: float = 15.0,
    ) -> None:
        self._snapshot = snapshot
        self._cancel_event = cancel_event
        self._dump_path = Path(dump_path)
        self._diagnostic_path = Path(diagnostic_path) if diagnostic_path else self._dump_path.with_name("amd_watchdog.jsonl")
        self._heartbeat_s = max(0.05, float(heartbeat_s))
        self._freeze_s = max(0.1, float(freeze_s))
        # Keep short injected test windows useful while production defaults
        # remain 2s/5s/15s as required by the AMD audit contract.
        self._warn_s = max(0.1, min(float(warn_s), self._freeze_s))
        self._detail_s = max(self._warn_s, float(detail_s))
        self._stop = threading.Event()
        self._active = threading.Event()
        self._active.set()
        self._lock = threading.Lock()
        self._completed = 0
        self._last_progress = time.monotonic()
        self._freeze_reported = False
        self._warn_reported = False
        self._detail_last_written = 0.0
        self.thread = threading.Thread(
            target=self._run, name="TeleM-AMD-Watchdog", daemon=True
        )

    @property
    def freeze_reported(self) -> bool:
        return self._freeze_reported

    def start(self) -> None:
        self.thread.start()

    def mark_completed(self, completed: int) -> None:
        with self._lock:
            if int(completed) > self._completed:
                self._completed = int(completed)
                self._last_progress = time.monotonic()

    def set_render_active(self, active: bool) -> None:
        if active:
            with self._lock:
                self._last_progress = time.monotonic()
            self._active.set()
        else:
            self._active.clear()

    def stop(self, timeout: float = 2.0) -> None:
        self._active.clear()
        self._stop.set()
        self.thread.join(timeout=max(0.0, timeout))

    @staticmethod
    def _tail_text(value: Any) -> str:
        if value is None:
            return "[]"
        lines = []
        for line in list(value):
            if isinstance(line, bytes):
                line = line.decode(errors="replace")
            lines.append(str(line).strip())
        return repr([line for line in lines if line])

    def _heartbeat(self, snap: dict[str, Any], completed: int) -> None:
        stage_id = int(snap.get("native_stage", 0) or 0)
        print(
            "[AMD HEARTBEAT] "
            f"frame={completed} decoded={snap.get('decoded', 0)} "
            f"produced={snap.get('produced', 0)} composed={snap.get('composed', 0)} "
            f"submitted={snap.get('submitted', 0)} encoded={snap.get('encoded', 0)} "
            f"written={snap.get('written', 0)} producer_q={snap.get('producer_q', 0)} "
            f"encoder_q={snap.get('encoder_q', 0)} "
            f"native_stage={NATIVE_STAGE_NAMES.get(stage_id, stage_id)} "
            f"last_native_stage_age={float(snap.get('native_stage_age_s', 0.0)):.3f}s "
            f"ffmpeg_alive={snap.get('ffmpeg_alive', False)} "
            f"render_thread_alive={snap.get('render_thread_alive', False)}",
            flush=True,
        )

    def _dump_threads(self) -> None:
        try:
            self._dump_path.parent.mkdir(parents=True, exist_ok=True)
            with self._dump_path.open("a", encoding="utf-8") as dump_file:
                dump_file.write(f"\n[AMD FREEZE THREAD DUMP] {time.ctime()}\n")
                dump_file.flush()
                faulthandler.dump_traceback(file=dump_file, all_threads=True)
            print(f"[AMD FREEZE DETECTED] thread_dump={self._dump_path}", flush=True)
        except Exception as exc:
            print(f"[AMD FREEZE DETECTED] faulthandler dump failed: {exc}", file=sys.stderr, flush=True)

    def _write_detail_snapshot(self, snap: dict[str, Any], completed: int, age: float) -> None:
        """Write stalled-pipeline detail off the console and off the render thread."""
        try:
            self._diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "time": time.time(),
                "completed": completed,
                "stall_age_s": round(age, 3),
                "snapshot": snap,
            }
            with self._diagnostic_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")
        except Exception as exc:
            print(f"[AMD WATCHDOG] diagnostic log failed: {exc}", file=sys.stderr, flush=True)

    def _freeze(self, snap: dict[str, Any], completed: int, age: float) -> None:
        stage_id = int(snap.get("native_stage", 0) or 0)
        print(
            "[AMD FREEZE DETECTED] "
            f"frame={completed} no_completed_frame_s={age:.3f} "
            f"native_frame={snap.get('native_frame', 0)} "
            f"native_stage={NATIVE_STAGE_NAMES.get(stage_id, stage_id)} "
            f"decoded={snap.get('decoded', 0)} produced={snap.get('produced', 0)} "
            f"composed={snap.get('composed', 0)} submitted={snap.get('submitted', 0)} "
            f"encoded={snap.get('encoded', 0)} written={snap.get('written', 0)} "
            f"producer_q={snap.get('producer_q', 0)} encoder_q={snap.get('encoder_q', 0)} "
            f"workers={snap.get('workers', {})} processes={snap.get('processes', {})} "
            f"stdout_tail={self._tail_text(snap.get('stdout_tail'))} "
            f"stderr_tail={self._tail_text(snap.get('stderr_tail'))}",
            flush=True,
        )
        self._dump_threads()

    def _run(self) -> None:
        next_heartbeat = time.monotonic() + self._heartbeat_s
        while not self._stop.wait(0.25):
            if not self._active.is_set():
                continue
            now = time.monotonic()
            with self._lock:
                completed = self._completed
                age = now - self._last_progress
            try:
                snap = self._snapshot()
            except Exception as exc:
                snap = {"snapshot_error": repr(exc)}
            stage_age = float(snap.get("native_stage_age_s", 0.0) or 0.0)
            stall_age = max(age, stage_age)
            if now >= next_heartbeat:
                self._heartbeat(snap, completed)
                next_heartbeat = now + self._heartbeat_s
            cancelled = bool(self._cancel_event is not None and self._cancel_event.is_set())
            if cancelled or stall_age < self._warn_s:
                self._warn_reported = False
                self._freeze_reported = False
                self._detail_last_written = 0.0
                continue
            if not self._warn_reported:
                self._warn_reported = True
                print(
                    f"[AMD WATCHDOG] render progress stalled >{self._warn_s:.0f}s "
                    f"frame={completed} native_stage={snap.get('native_stage', 'unknown')} "
                    f"age={stall_age:.3f}s",
                    flush=True,
                )
            if stall_age >= self._detail_s and (self._detail_last_written == 0.0 or now - self._detail_last_written >= self._heartbeat_s):
                self._detail_last_written = now
                self._write_detail_snapshot(snap, completed, stall_age)
            if stall_age >= self._freeze_s and not self._freeze_reported:
                self._freeze_reported = True
                self._freeze(snap, completed, stall_age)
