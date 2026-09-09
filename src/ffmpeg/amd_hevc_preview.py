"""Best-effort AMD export preview implementations.

The final mux path owns the encoded stream.  This module is only a bounded,
best-effort consumer.  Production AMD Preview uses the native D3D11 frame tap;
the older HEVC sidecar remains available for diagnostics only.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import ctypes
from collections import deque
from typing import Callable, Optional


class AMDGPUNativeFrameTapPreview:
    """Latest-state AMD export preview fed by the native D3D11 frame tap.

    The native DLL owns the GPU capture, downscale and asynchronous staging
    readback.  This object only polls a completed BGRA frame after a normal
    render call and forwards the newest frame to Qt; it creates no process,
    decoder, queue or worker thread.
    """

    is_native_frame_tap = True

    def __init__(
        self,
        *,
        width: int = 1280,
        height: int = 720,
        target_fps: float = 2.0,
        on_frame: Optional[Callable[[bytes, int, int], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.width = max(2, int(width) & ~1)
        self.height = max(2, int(height) & ~1)
        self.target_fps = max(0.25, float(target_fps))
        self.on_frame = on_frame
        self.on_error = on_error
        self._lock = threading.RLock()
        self._started = False
        self._disabled = False
        self._native_dll = None
        self._native_handle = None
        self._buffer = ctypes.create_string_buffer(self.width * self.height * 4)
        self._fps_num = 30
        self._fps_den = 1
        self._interval_frames = 15
        self._updates = 0
        self._dropped = 0
        self._last_error = ""
        self._capture_times_ms: list[float] = []
        self._last_frame = -1
        self._capture_inflight = False
        self._gui_pending = 0

    def configure_input_rate(self, fps_num: int, fps_den: int) -> None:
        with self._lock:
            self._fps_num = max(1, int(fps_num))
            self._fps_den = max(1, int(fps_den))
            interval = (self._fps_num / self._fps_den) / self.target_fps
            self._interval_frames = max(1, int(round(interval)))

    def start(self) -> bool:
        with self._lock:
            if self._disabled:
                return False
            self._started = True
            self._updates = 0
            self._dropped = 0
            self._last_error = ""
            self._capture_times_ms.clear()
            self._last_frame = -1
            print(
                f"[EXPORT PREVIEW GPU TAP START] size={self.width}x{self.height} "
                f"target_fps={self.target_fps:g}",
                flush=True,
            )
            return True

    def bind_native(self, native_dll: object, native_handle: object) -> bool:
        """Attach to one render context and enable its native tap."""
        with self._lock:
            self._native_dll = native_dll
            self._native_handle = native_handle
        setter = getattr(native_dll, "telem_amd_set_preview_tap", None)
        poller = getattr(native_dll, "telem_amd_poll_preview_tap", None)
        if setter is None or poller is None:
            self._fail("native GPU frame tap ABI unavailable")
            return False
        try:
            setter.restype = ctypes.c_int
            setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint,
                               ctypes.c_uint, ctypes.c_uint]
            poller.restype = ctypes.c_int
            poller.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint,
                ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_double),
            ]
            ok = int(setter(
                native_handle, 1, self.width, self.height,
                max(1, self._interval_frames),
            ))
        except Exception as exc:  # Preview must not break final render.
            self._fail(f"native GPU frame tap setup: {exc}")
            return False
        if not ok:
            self._fail("native GPU frame tap setup failed")
            return False
        with self._lock:
            self._capture_inflight = False
        print(
            f"[EXPORT PREVIEW] enabled=True backend=gpu_frame_tap "
            f"target_fps={self.target_fps:g} target_size={self.width}x{self.height}",
            flush=True,
        )
        return True

    def poll_native_frame(self) -> bool:
        """Poll one completed readback without flushing or waiting for GPU."""
        with self._lock:
            if not self._started or self._disabled:
                return False
            native_dll = self._native_dll
            native_handle = self._native_handle
        poller = getattr(native_dll, "telem_amd_poll_preview_tap", None)
        if poller is None or native_handle is None:
            return False
        out_w = ctypes.c_uint(0)
        out_h = ctypes.c_uint(0)
        out_frame = ctypes.c_uint(0)
        readback_ms = ctypes.c_double(0.0)
        try:
            ready = int(poller(
                native_handle,
                ctypes.cast(self._buffer, ctypes.POINTER(ctypes.c_uint8)),
                ctypes.c_uint(len(self._buffer)),
                ctypes.byref(out_w), ctypes.byref(out_h),
                ctypes.byref(out_frame), ctypes.byref(readback_ms),
            ))
        except Exception as exc:
            self._fail(f"native GPU frame tap poll: {exc}")
            return False
        if not ready:
            return False
        raw = bytes(self._buffer.raw[: int(out_w.value) * int(out_h.value) * 4])
        with self._lock:
            self._updates += 1
            self._last_frame = int(out_frame.value)
            self._capture_inflight = False
            self._capture_times_ms.append(float(readback_ms.value))
            if len(self._capture_times_ms) > 120:
                del self._capture_times_ms[:-120]
            callback = self.on_frame
        if callback is not None:
            try:
                callback(raw, int(out_w.value), int(out_h.value))
            except Exception as exc:
                self._fail(f"GPU frame tap callback: {exc}")
        return True

    def accept_external_frame(self, raw: bytes, width: int, height: int) -> None:
        """Accept a frame read back by an isolated AMD child process.

        The GUI owns this lightweight session only for latest-state statistics
        and Qt delivery; the native DLL handle always remains in the child.
        """
        with self._lock:
            if not self._started or self._disabled:
                return
            self._updates += 1
            self._last_frame += 1
            callback = self.on_frame
        if callback is not None:
            try:
                callback(bytes(raw), int(width), int(height))
            except Exception as exc:
                self._fail(f"external GPU frame tap callback: {exc}")

    def feed(self, _payload: bytes) -> bool:
        """Compatibility no-op: the production tap never consumes HEVC."""
        return True

    def finish_input(self, timeout: float = 0.0) -> None:
        del timeout

    def stop(self, reason: str = "render_end", *, drain: bool = False) -> None:
        del drain
        with self._lock:
            native_dll = self._native_dll
            native_handle = self._native_handle
            self._started = False
        setter = getattr(native_dll, "telem_amd_set_preview_tap", None)
        if setter is not None and native_handle is not None:
            try:
                setter(native_handle, 0, self.width, self.height, 0)
            except Exception:
                pass
        print(f"[EXPORT PREVIEW GPU TAP STOP] reason={reason}", flush=True)

    def _fail(self, message: str) -> None:
        with self._lock:
            if not self._last_error:
                self._last_error = str(message)
            self._disabled = True
            self._started = False
            callback = self.on_error
        print(f"[EXPORT PREVIEW GPU TAP ERROR] {message}", flush=True)
        if callback is not None:
            try:
                callback(str(message))
            except Exception:
                pass

    def stats(self) -> dict[str, object]:
        with self._lock:
            samples = list(self._capture_times_ms)
            mean_ms = sum(samples) / len(samples) if samples else 0.0
            return {
                "enabled": self._started and not self._disabled,
                "started": self._started,
                "backend": "gpu_frame_tap",
                "pid": None,
                "alive": False,
                "width": self.width,
                "height": self.height,
                "fps": self.target_fps,
                "updates": self._updates,
                "dropped": self._dropped,
                "dropped_chunks": self._dropped,
                "capture_inflight": int(self._capture_inflight),
                "avg_capture_ms": mean_ms,
                "max_capture_ms": max(samples) if samples else 0.0,
                "gui_pending": self._gui_pending,
                "cpu_readback_ms": mean_ms,
                "restarts": 0,
                "last_frame": self._last_frame,
                "last_error": self._last_error,
                "workers": 0,
            }


class AMDContinuousHEVCPreview:
    """One FFmpeg HEVC decoder producing latest-only raw preview frames."""

    def __init__(
        self,
        *,
        ffmpeg_exe: str,
        width: int = 1280,
        height: int = 720,
        output_fps: float = 1.0,
        on_frame: Optional[Callable[[bytes, int, int], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        queue_chunks: int = 256,
    ) -> None:
        self.ffmpeg_exe = str(ffmpeg_exe)
        self.width = max(2, int(width))
        self.height = max(2, int(height))
        self.output_fps = max(0.1, float(output_fps))
        self.on_frame = on_frame
        self.on_error = on_error
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max(2, int(queue_chunks)))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._process: subprocess.Popen | None = None
        self._writer: threading.Thread | None = None
        self._reader: threading.Thread | None = None
        self._stderr: threading.Thread | None = None
        self._started = False
        self._disabled = False
        self._fault_injected = False
        self._frames = 0
        self._dropped_chunks = 0
        self._input_chunks = 0
        self._restarts = 0
        self._first_frame_mono = 0.0
        self._last_frame_mono = 0.0
        self._last_error = ""
        self._stderr_lines: deque[str] = deque(maxlen=40)
        self._last_resource_sample_mono = 0.0
        self._cpu_samples: list[float] = []
        self._rss_peak_bytes = 0
        self._fps_num = 30
        self._fps_den = 1
        self._input_closed = False

    def configure_input_rate(self, fps_num: int, fps_den: int) -> None:
        with self._lock:
            self._fps_num = max(1, int(fps_num))
            self._fps_den = max(1, int(fps_den))

    def command(self) -> list[str]:
        brightness = os.environ.get("AMD_EXPORT_PREVIEW_BRIGHTNESS", "-0.08")
        vf = (
            f"fps={self.output_fps:g},"
            f"scale={self.width}:{self.height}:flags=bicubic,"
            f"eq=brightness={brightness}"
        )
        # Keep the sidecar deliberately lightweight.  The final AMF/mux path
        # owns the CPU budget; a second decoder thread can add enough
        # contention to back-pressure the producer on short renders.
        threads = max(1, int(os.environ.get("AMD_EXPORT_PREVIEW_THREADS", "1")))
        return [
            self.ffmpeg_exe,
            "-hide_banner", "-loglevel", "error",
            "-threads", str(threads),
            "-filter_threads", "1",
            "-f", "hevc",
            "-r", f"{self._fps_num}/{self._fps_den}",
            "-i", "pipe:0",
            "-vf", vf,
            "-pix_fmt", "bgra",
            "-f", "rawvideo",
            "pipe:1",
        ]

    def start(self) -> bool:
        with self._lock:
            if self._started and self._process is not None and self._process.poll() is None:
                return True
            if self._disabled:
                return False
            self._stop.clear()
            self._input_closed = False
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            try:
                creationflags = 0x00004000 if os.name == "nt" else 0  # BELOW_NORMAL_PRIORITY_CLASS
                proc = subprocess.Popen(
                    self.command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                    creationflags=creationflags,
                )
            except Exception as exc:  # preview failure must not affect final export
                self._fail(f"start: {exc}")
                return False
            self._process = proc
            self._started = True
            self._frames = 0
            self._last_resource_sample_mono = 0.0
            self._cpu_samples.clear()
            self._rss_peak_bytes = 0
            self._first_frame_mono = 0.0
            self._last_frame_mono = 0.0
            self._writer = threading.Thread(
                target=self._writer_loop,
                name="TeleM-AMD-HEVC-Preview-Writer",
                daemon=True,
            )
            self._reader = threading.Thread(
                target=self._reader_loop,
                name="TeleM-AMD-HEVC-Preview-Reader",
                daemon=True,
            )
            self._stderr = threading.Thread(
                target=self._stderr_loop,
                name="TeleM-AMD-HEVC-Preview-Stderr",
                daemon=True,
            )
            self._writer.start()
            self._reader.start()
            self._stderr.start()
            print(
                f"[EXPORT PREVIEW FFMPEG START] size={self.width}x{self.height} "
                f"fps={self.output_fps:g} cmd={' '.join(self.command())}",
                flush=True,
            )
            return True

    def feed(self, payload: bytes) -> bool:
        """Queue an encoded chunk without ever blocking the final mux thread."""
        if not payload:
            return True
        with self._lock:
            proc = self._process
            active = self._started and not self._disabled and not self._stop.is_set()
            if not active or proc is None or proc.poll() is not None:
                return False
            if (
                os.environ.get(
                    "AMD_EXPORT_PREVIEW_FFMPEG_FAULT",
                    os.environ.get(
                        "AMD_EXPORT_PREVIEW_FAULT_INJECTION",
                        os.environ.get("TELEM_EXPORT_PREVIEW_FAULT_INJECTION", "0"),
                    ),
                ) == "1"
                and not self._fault_injected
            ):
                self._fault_injected = True
                try:
                    proc.kill()
                except Exception:
                    pass
                self._fail("fault injection")
                return False
            try:
                self._queue.put_nowait(payload if isinstance(payload, bytes) else bytes(payload))
            except queue.Full:
                self._dropped_chunks += 1
                self._fail("bounded input queue full; preview disabled")
                return False
            self._input_chunks += 1
            # Sampling is throttled and happens on the existing producer call
            # path, so it cannot add a worker or alter render synchronization.
            now_mono = time.monotonic()
            if now_mono - self._last_resource_sample_mono >= 0.25:
                self._last_resource_sample_mono = now_mono
                try:
                    import psutil
                    child = psutil.Process(proc.pid)
                    cpu = float(child.cpu_percent(None))
                    rss = int(child.memory_info().rss)
                    self._cpu_samples.append(cpu)
                    if len(self._cpu_samples) > 120:
                        del self._cpu_samples[:-120]
                    self._rss_peak_bytes = max(self._rss_peak_bytes, rss)
                except Exception:
                    pass
            return True

    def finish_input(self, timeout: float = 8.0) -> None:
        """Drain queued HEVC, close preview stdin, then wait briefly for frames."""
        with self._lock:
            if not self._started:
                return
            self._input_closed = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            self._stop.set()
        writer = self._writer
        if writer is not None:
            writer.join(timeout=max(0.1, float(timeout)))
        proc = self._process
        if proc is not None:
            try:
                proc.wait(timeout=max(0.1, float(timeout)))
            except subprocess.TimeoutExpired:
                self._fail("finish timeout")
                try:
                    proc.kill()
                except Exception:
                    pass
        self._join_threads(timeout=1.0)
        self._mark_stopped()

    def stop(self, reason: str = "render_end", *, drain: bool = False) -> None:
        if drain:
            self.finish_input()
            return
        with self._lock:
            if not self._started:
                return
            self._stop.set()
            proc = self._process
            self._disabled = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        self._join_threads(timeout=1.0)
        self._mark_stopped()
        print(f"[EXPORT PREVIEW FFMPEG STOP] reason={reason}", flush=True)

    def _writer_loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if payload is None:
                break
            proc = self._process
            if proc is None or proc.stdin is None:
                break
            try:
                proc.stdin.write(payload)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self._fail(f"stdin: {exc}")
                break
        proc = self._process
        if proc is not None and proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass

    def _reader_loop(self) -> None:
        frame_size = self.width * self.height * 4
        while not self._stop.is_set():
            proc = self._process
            if proc is None or proc.stdout is None:
                break
            buf = bytearray()
            try:
                while len(buf) < frame_size and not self._stop.is_set():
                    part = proc.stdout.read(frame_size - len(buf))
                    if not part:
                        break
                    buf.extend(part)
            except (OSError, ValueError) as exc:
                self._fail(f"stdout: {exc}")
                break
            if len(buf) != frame_size:
                if not self._stop.is_set() and not self._input_closed:
                    self._fail("partial rawvideo frame")
                break
            now = time.monotonic()
            with self._lock:
                self._frames += 1
                if self._first_frame_mono == 0.0:
                    self._first_frame_mono = now
                self._last_frame_mono = now
            callback = self.on_frame
            if callback is not None:
                try:
                    callback(bytes(buf), self.width, self.height)
                except Exception as exc:
                    self._fail(f"frame callback: {exc}")

    def _stderr_loop(self) -> None:
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    with self._lock:
                        self._stderr_lines.append(text)
        except Exception:
            pass

    def _fail(self, message: str) -> None:
        with self._lock:
            if not self._last_error:
                self._last_error = str(message)
            already = self._disabled
            self._disabled = True
            self._stop.set()
        if not already:
            print(f"[EXPORT PREVIEW FFMPEG ERROR] {message}", flush=True)
            callback = self.on_error
            if callback is not None:
                try:
                    callback(str(message))
                except Exception:
                    pass

    def _join_threads(self, timeout: float) -> None:
        current = threading.current_thread()
        for thread in (self._writer, self._reader, self._stderr):
            if thread is not None and thread is not current:
                thread.join(timeout=max(0.05, float(timeout)))

    def _mark_stopped(self) -> None:
        with self._lock:
            self._started = False
            self._stop.set()
            self._process = None

    def stats(self) -> dict[str, object]:
        with self._lock:
            proc = self._process
            pid = proc.pid if proc is not None else None
            alive = bool(proc is not None and proc.poll() is None)
            cpu_percent = None
            rss_bytes = None
            if pid is not None and alive:
                try:
                    import psutil
                    child = psutil.Process(pid)
                    cpu_percent = child.cpu_percent(None)
                    rss_bytes = child.memory_info().rss
                except Exception:
                    pass
            cpu_mean = (
                sum(self._cpu_samples) / len(self._cpu_samples)
                if self._cpu_samples else None
            )
            cpu_peak = max(self._cpu_samples) if self._cpu_samples else None
            return {
                "enabled": not self._disabled,
                "started": self._started,
                "pid": pid,
                "alive": alive,
                "cpu_percent": cpu_percent,
                "rss_bytes": rss_bytes,
                "cpu_percent_mean": cpu_mean,
                "cpu_percent_peak": cpu_peak,
                "rss_peak_bytes": self._rss_peak_bytes or None,
                "width": self.width,
                "height": self.height,
                "fps": self.output_fps,
                "updates": self._frames,
                "input_chunks": self._input_chunks,
                "dropped_chunks": self._dropped_chunks,
                "restarts": self._restarts,
                "last_error": self._last_error,
                "stderr": list(self._stderr_lines)[-5:],
            }
