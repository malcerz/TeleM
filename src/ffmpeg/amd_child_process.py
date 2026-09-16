"""Short-lived AMD export worker and bounded parent/child IPC.

The AMD native renderer deliberately lives in a fresh Windows ``spawn``
process for every export.  This makes process exit the reclamation boundary for
Media Foundation, D3D11, DXGI, AMF and vendor-owned allocations.  The parent
GUI never imports a native handle from this module; it only receives bounded
progress/preview messages and a terminal result.
"""

from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path
import pickle
import queue
import subprocess
import sys
import threading
import time
import traceback
from typing import Any, Callable, Optional


def _qualified_type(value: Any) -> str:
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _find_lazy_sample_lists(root: Any) -> list[dict[str, Any]]:
    """Describe LazySampleList locations without reading their sample values."""
    from src.telemetry_processed_cache import LazySampleList

    found: list[dict[str, Any]] = []
    seen: set[int] = set()

    def visit(value: Any, path: str, depth: int = 0) -> None:
        if isinstance(value, LazySampleList):
            arr = value._arr
            found.append({
                "path": path,
                "state": "materialized" if value._materialized else "lazy",
                "count": len(value),
                "array_bytes": int(arr.nbytes) if arr is not None else 0,
            })
            return
        if depth >= 10 or value is None or isinstance(
            value, (str, bytes, bytearray, int, float, bool, complex, Path)
        ):
            return
        value_id = id(value)
        if value_id in seen:
            return
        seen.add(value_id)
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f"{path}.{key}", depth + 1)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            # Ordinary telemetry sample lists contain scalar/datetime tuples;
            # LazySampleList instances are caught before this branch.
            for index, item in enumerate(value):
                if index >= 256:
                    break
                visit(item, f"{path}[{index}]", depth + 1)
            return
        try:
            attributes = vars(value)
        except TypeError:
            return
        for name, item in attributes.items():
            visit(item, f"{path}.{name}", depth + 1)

    visit(root, "render_job")
    return found


def _private_memory_bytes() -> Optional[int]:
    """Return current Windows private bytes without adding a dependency."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = psapi.GetProcessMemoryInfo
        get_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        get_info.restype = wintypes.BOOL
        ok = get_info(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return int(counters.PrivateUsage) if ok else None
    except Exception:
        return None


def _fd_is_valid(fd: Any) -> bool:
    """Return whether *fd* still refers to an open OS descriptor."""
    try:
        os.fstat(int(fd))
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _stream_is_usable(stream: Any) -> bool:
    """Check a Python stream without relying on stderr for diagnostics."""
    if stream is None or bool(getattr(stream, "closed", False)):
        return False
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, TypeError, ValueError):
        # StringIO-like streams are valid even though they have no OS fd.
        return True
    return _fd_is_valid(fd)


def _windows_fd_info(fd: int) -> dict[str, Any]:
    """Return best-effort HANDLE validity details for a file descriptor."""
    result: dict[str, Any] = {"fd": int(fd), "fileno_valid": _fd_is_valid(fd)}
    if os.name != "nt":
        return result
    try:
        import ctypes
        from ctypes import wintypes
        import msvcrt

        handle = msvcrt.get_osfhandle(int(fd))
        result["handle"] = int(handle)
        if handle in (-1, 0):
            result.update({"get_file_type": 0, "handle_valid": False})
            return result
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetFileType.argtypes = [wintypes.HANDLE]
        kernel32.GetFileType.restype = wintypes.DWORD
        kernel32.GetHandleInformation.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)
        ]
        kernel32.GetHandleInformation.restype = wintypes.BOOL
        flags = wintypes.DWORD()
        file_type = int(kernel32.GetFileType(wintypes.HANDLE(handle)))
        handle_ok = bool(
            kernel32.GetHandleInformation(wintypes.HANDLE(handle), ctypes.byref(flags))
        )
        result.update({
            "get_file_type": file_type,
            "handle_valid": bool(file_type) and handle_ok,
            "handle_flags": int(flags.value) if handle_ok else None,
        })
    except Exception as exc:
        result["handle_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _child_handle_diagnostics_enabled() -> bool:
    value = os.environ.get("AMD_CHILD_HANDLE_DIAGNOSTICS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _write_diagnostic_line(path: Path, text: str) -> None:
    """Write diagnostics through an independent low-level file descriptor."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd: Optional[int] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), flags, 0o644)
        payload = (str(text).rstrip("\r\n") + "\n").encode("utf-8", errors="replace")
        os.write(fd, payload)
    except (OSError, ValueError):
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _stream_snapshot(label: str, stream: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "label": label,
        "type": _qualified_type(stream) if stream is not None else "None",
        "usable": _stream_is_usable(stream),
    }
    try:
        fd = int(stream.fileno())
    except (AttributeError, OSError, TypeError, ValueError):
        fd = None
    info["fileno"] = fd
    if fd is not None:
        info["handle"] = _windows_fd_info(fd)
    return info


class _ChildStdioRedirect:
    """Own child stdio redirection and restore streams before log close.

    ``multiprocessing.spawn`` can inherit ``None`` or a closed Windows console
    stream.  Python flushes ``sys.stdout``/``sys.stderr`` during interpreter
    finalization, so leaving either object closed produces exit status 120.
    The guard keeps independent log wrappers alive, restores a usable stream
    (or an open ``os.devnull`` sink), and only then allows the diagnostic file
    to close.
    """

    def __init__(self, log_file: Any) -> None:
        self.log_file = log_file
        self._saved: Optional[tuple[Any, Any, Any, Any]] = None
        self._log_stdout: Any = None
        self._log_stderr: Any = None
        self._safe_stdout: Any = None
        self._safe_stderr: Any = None
        self._restored = False

    def redirect(self) -> None:
        self._saved = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
        try:
            os.dup2(self.log_file.fileno(), 1)
        except (OSError, ValueError):
            pass
        try:
            os.dup2(self.log_file.fileno(), 2)
        except (OSError, ValueError):
            pass
        self._log_stdout = os.fdopen(
            os.dup(self.log_file.fileno()), "a", encoding="utf-8", buffering=1
        )
        self._log_stderr = os.fdopen(
            os.dup(self.log_file.fileno()), "a", encoding="utf-8", buffering=1
        )
        sys.stdout = self._log_stdout
        sys.stderr = self._log_stderr

    def _safe_stream(self, current: Any, which: str) -> Any:
        if _stream_is_usable(current):
            return current
        attr = "_safe_stdout" if which == "stdout" else "_safe_stderr"
        value = getattr(self, attr)
        if value is None or not _stream_is_usable(value):
            value = open(os.devnull, "w", encoding="utf-8", buffering=1)
            setattr(self, attr, value)
        return value

    def restore(self) -> None:
        if self._restored:
            return
        self._restored = True
        saved = self._saved
        if saved is None:
            return
        for stream in (self._log_stdout, self._log_stderr):
            try:
                if stream is not None:
                    stream.flush()
            except (OSError, ValueError):
                pass
        stdout = self._safe_stream(saved[0], "stdout")
        stderr = self._safe_stream(saved[1], "stderr")
        sys.stdout = stdout
        sys.stderr = stderr
        sys.__stdout__ = self._safe_stream(saved[2], "stdout")
        sys.__stderr__ = self._safe_stream(saved[3], "stderr")
        for stream in (self._log_stdout, self._log_stderr):
            try:
                if stream is not None and stream not in (stdout, stderr):
                    stream.close()
            except (OSError, ValueError):
                pass
def inspect_render_job_pickle(render_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Validate and measure the exact data object handed to Windows spawn."""
    lazy_fields = _find_lazy_sample_lists(render_kwargs)
    top_level_types = {
        str(key): _qualified_type(value) for key, value in render_kwargs.items()
    }
    private_before = _private_memory_bytes()
    started = time.perf_counter()
    payload = pickle.dumps(render_kwargs, protocol=pickle.HIGHEST_PROTOCOL)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    private_after = _private_memory_bytes()
    payload_size = len(payload)
    del payload
    if private_before is not None:
        import gc
        gc.collect()
    private_released = _private_memory_bytes()
    result = {
        "pickle_size": payload_size,
        "pickle_time_ms": elapsed_ms,
        "private_memory_delta": (
            private_after - private_before
            if private_before is not None and private_after is not None
            else None
        ),
        "private_memory_retained_delta": (
            private_released - private_before
            if private_before is not None and private_released is not None
            else None
        ),
        "top_level_types": top_level_types,
        "lazy_sample_lists": lazy_fields,
    }
    print(
        "[AMD CHILD JOB PICKLE] "
        f"size_bytes={result['pickle_size']} time_ms={elapsed_ms:.3f} "
        f"parent_private_peak_delta_bytes={result['private_memory_delta']} "
        f"parent_private_retained_delta_bytes="
        f"{result['private_memory_retained_delta']}",
        flush=True,
    )
    print(f"[AMD CHILD JOB TYPES] {top_level_types}", flush=True)
    print(f"[AMD CHILD JOB LAZY] {lazy_fields}", flush=True)
    return result


class _ChildCancelState:
    """Cancellation state owned by the child, fed only by IPC messages."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.event = threading.Event()
        self.reason = "NONE"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.thread = threading.Thread(
            target=self._listen,
            name="TeleM-AMD-Child-Control",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self._stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=0.5)

    def _listen(self) -> None:
        while not self._stop.is_set():
            try:
                if not self._conn.poll(0.1):
                    continue
                message = self._conn.recv()
            except (EOFError, OSError, BrokenPipeError):
                with self._lock:
                    self.reason = "PARENT_EXIT_EOF"
                self.event.set()
                print(
                    f"[PROC] parent EOF detected, cancel triggered for child pid={os.getpid()}",
                    flush=True,
                )
                return
            if not isinstance(message, dict) or message.get("kind") != "cancel":
                continue
            with self._lock:
                self.reason = str(message.get("reason") or "INTERNAL_STOP")
            self.event.set()
            print(
                f"[AMD CHILD] cancel received reason={self.reason}",
                flush=True,
            )
            return

    def reason_value(self) -> str:
        with self._lock:
            return self.reason


class _ParentDeathWatchdog:
    """Lightweight watchdog detecting parent process termination."""

    def __init__(self, parent_pid: int, cancel_state: _ChildCancelState) -> None:
        self.parent_pid = int(parent_pid)
        self.cancel_state = cancel_state
        self._stop = threading.Event()
        self.thread = threading.Thread(
            target=self._watch,
            name="TeleM-AMD-ParentDeathWatchdog",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self._stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=0.5)

    def _watch(self) -> None:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            SYNCHRONIZE = 0x00100000
            h_parent = kernel32.OpenProcess(SYNCHRONIZE, False, self.parent_pid)
            if not h_parent:
                print(f"[PROC] parent death detected (cannot open parent pid={self.parent_pid})", flush=True)
                with self.cancel_state._lock:
                    self.cancel_state.reason = "PARENT_PROCESS_EXIT"
                self.cancel_state.event.set()
                return

            try:
                while not self._stop.is_set():
                    res = kernel32.WaitForSingleObject(h_parent, 500)
                    if res == 0:  # WAIT_OBJECT_0: parent died
                        print(f"[PROC] parent death detected pid={self.parent_pid}", flush=True)
                        with self.cancel_state._lock:
                            self.cancel_state.reason = "PARENT_PROCESS_EXIT"
                        self.cancel_state.event.set()
                        return
                    elif res != 0x102:  # not WAIT_TIMEOUT
                        break
            finally:
                kernel32.CloseHandle(h_parent)
        else:
            while not self._stop.is_set():
                time.sleep(0.5)
                try:
                    if os.getppid() != self.parent_pid:
                        print(f"[PROC] parent death detected (ppid changed from {self.parent_pid})", flush=True)
                        with self.cancel_state._lock:
                            self.cancel_state.reason = "PARENT_PROCESS_EXIT"
                        self.cancel_state.event.set()
                        return
                except Exception:
                    pass


class _ChildIpcEmitter:
    """Single-writer IPC endpoint with latest-only preview state."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self._control: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=128)
        self._preview_lock = threading.Lock()
        self._latest_preview: Optional[dict[str, Any]] = None
        self._stop = threading.Event()
        self._closed = threading.Event()
        self.thread = threading.Thread(
            target=self._writer_loop,
            name="TeleM-AMD-Child-IPC",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def send(self, message: dict[str, Any], *, critical: bool = False) -> None:
        if self._closed.is_set():
            return
        if critical:
            try:
                self._control.put(message, timeout=5.0)
            except queue.Full:
                self._closed.set()
            return
        try:
            self._control.put_nowait(message)
        except queue.Full:
            # Progress is advisory.  Drop an older progress update while
            # retaining warnings and terminal messages.
            try:
                old = self._control.get_nowait()
            except queue.Empty:
                return
            if old.get("kind") != "progress":
                try:
                    self._control.put_nowait(old)
                except queue.Full:
                    pass
            try:
                self._control.put_nowait(message)
            except queue.Full:
                pass

    def preview(self, raw: bytes, width: int, height: int) -> None:
        if self._closed.is_set():
            return
        with self._preview_lock:
            self._latest_preview = {
                "kind": "preview",
                "payload": bytes(raw),
                "width": int(width),
                "height": int(height),
            }

    def close(self) -> None:
        self._stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=3.0)
        self._closed.set()
        try:
            self.conn.close()
        except Exception:
            pass

    def _writer_loop(self) -> None:
        while not self._stop.is_set() or not self._control.empty():
            message: Optional[dict[str, Any]] = None
            try:
                message = self._control.get(timeout=0.05)
            except queue.Empty:
                with self._preview_lock:
                    message = self._latest_preview
                    self._latest_preview = None
            if message is None:
                continue
            try:
                self.conn.send(message)
            except (EOFError, OSError, BrokenPipeError):
                self._closed.set()
                return


class AMDChildProcessHandle:
    """Popen-like facade used by existing GUI/finalization code."""

    stdin = None

    def __init__(self, process: mp.Process, conn: Any, log_path: Path) -> None:
        self._process = process
        self._conn = conn
        self.log_path = Path(log_path)
        self.pid = process.pid
        self._cancel_sent = False

    @property
    def returncode(self) -> Optional[int]:
        return self._process.exitcode

    def poll(self) -> Optional[int]:
        if self._process.is_alive():
            return None
        return self._process.exitcode

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    def cancel(self, reason: str) -> None:
        if self._cancel_sent or self.poll() is not None:
            return
        self._cancel_sent = True
        try:
            self._conn.send({"kind": "cancel", "reason": str(reason)})
        except (EOFError, OSError, BrokenPipeError):
            pass


def _tail(path: Path, limit: int = 12000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _connection_has_data(conn: Any, timeout: float = 0.0) -> bool:
    """Poll an IPC pipe after peer shutdown without leaking Windows errors."""
    try:
        return bool(conn.poll(timeout))
    except (EOFError, OSError, BrokenPipeError):
        return False


class _ParentIpcReader:
    """Read complete framed messages off the child pipe on a daemon thread.

    ``Connection.poll()`` only reports that bytes are readable.  Keeping the
    potentially blocking ``recv()`` off the render worker lets the parent
    reconcile process death, EOF, and a missing terminal message within a
    bounded deadline.
    """

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.messages: queue.Queue[Any] = queue.Queue(maxsize=256)
        self.eof = threading.Event()
        self.error: Optional[str] = None
        self.thread = threading.Thread(
            target=self._run,
            name="TeleM-AMD-Parent-IPC",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)

    def _run(self) -> None:
        try:
            while True:
                message = self.conn.recv()
                while True:
                    try:
                        self.messages.put(message, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except (EOFError, OSError, BrokenPipeError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.eof.set()


def _child_entry(
    render_kwargs: dict[str, Any],
    preview_config: Optional[dict[str, Any]],
    conn: Any,
    diagnostics_path: str,
    spawn_started_at: float,
    parent_pid: Optional[int] = None,
) -> None:
    """Spawn target.  Keep this top-level for Windows multiprocessing spawn."""

    if parent_pid is None:
        parent_pid = int(render_kwargs.get("_parent_pid") or os.getppid())

    log_path = Path(diagnostics_path)
    emitter = _ChildIpcEmitter(conn)
    # Start IPC before any filesystem/stdio setup so bootstrap failures always
    # have a primary error channel independent of stderr.
    emitter.start()
    cancel = _ChildCancelState(conn)
    watchdog = _ParentDeathWatchdog(parent_pid, cancel)
    preview_session: Any = None
    log_file: Any = None
    stdio_guard: Optional[_ChildStdioRedirect] = None
    child_phase = "bootstrap/startup"
    try:
        if _child_handle_diagnostics_enabled():
            _write_diagnostic_line(
                log_path,
                f"[AMD CHILD HANDLE] phase=entry pid={os.getpid()} "
                f"stdout={_stream_snapshot('stdout', sys.stdout)} "
                f"stderr={_stream_snapshot('stderr', sys.stderr)} "
                f"fd1={_windows_fd_info(1)} fd2={_windows_fd_info(2)}",
            )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open(
            "a" if _child_handle_diagnostics_enabled() else "w",
            encoding="utf-8",
            buffering=1,
        )
        # Redirect both Python and native C stdio.  Native DLL diagnostics
        # remain available after an access violation even without WER output.
        stdio_guard = _ChildStdioRedirect(log_file)
        stdio_guard.redirect()
        if _child_handle_diagnostics_enabled():
            _write_diagnostic_line(
                log_path,
                f"[AMD CHILD HANDLE] phase=after_redirect pid={os.getpid()} "
                f"stdout={_stream_snapshot('stdout', sys.stdout)} "
                f"stderr={_stream_snapshot('stderr', sys.stderr)} "
                f"fd1={_windows_fd_info(1)} fd2={_windows_fd_info(2)}",
            )
        os.environ["TELEM_AMD_CHILD_PROCESS"] = "1"
        generation_id = int(render_kwargs.get("generation_id", 0) or 0)
        print(f"[AMD CHILD START] child_pid={os.getpid()}", flush=True)
        print(
            f"[AMD CHILD JOB RESTORED] generation={generation_id}",
            flush=True,
        )
        emitter.send({
            "kind": "job_restored",
            "generation": generation_id,
            "child_pid": os.getpid(),
            "startup_ms": (time.perf_counter() - spawn_started_at) * 1000.0,
        }, critical=True)
        cancel.start()
        watchdog.start()

        def progress_cb(value: Any, text: Any) -> None:
            emitter.send({
                "kind": "progress_text",
                "value": value,
                "text": str(text),
            })

        def render_progress(
            completed: Any,
            total: Any,
            elapsed: Any,
            fps: Any,
            hud_state: Any,
        ) -> None:
            emitter.send({
                "kind": "progress",
                "completed": int(completed or 0),
                "total": int(total or 0),
                "elapsed": float(elapsed or 0.0),
                "fps": float(fps or 0.0),
                "hud_state": hud_state if isinstance(hud_state, dict) else {},
            })

        if preview_config and bool(preview_config.get("enabled")):
            from src.ffmpeg.amd_hevc_preview import AMDGPUNativeFrameTapPreview

            preview_session = AMDGPUNativeFrameTapPreview(
                width=int(preview_config.get("width", 960)),
                height=int(preview_config.get("height", 540)),
                target_fps=float(preview_config.get("target_fps", 2.0)),
                on_frame=emitter.preview,
                on_error=lambda message: emitter.send({
                    "kind": "warning", "text": str(message),
                }),
            )

        child_kwargs = dict(render_kwargs)
        child_kwargs.update({
            "progress_cb": progress_cb,
            "on_render_progress": render_progress,
            "cancel_event": cancel.event,
            "cancel_reason_provider": cancel.reason_value,
            "preview_state_provider": None,
            "preview_session": preview_session,
            "active_process_holder": {},
        })

        from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

        child_phase = "render"
        print(f"[AMD CHILD RENDER START] generation={generation_id}", flush=True)
        result = stream_overlay_to_ffmpeg(**child_kwargs)
        if cancel.event.is_set():
            emitter.send({
                "kind": "cancelled",
                "reason": cancel.reason_value(),
            }, critical=True)
        else:
            emitter.send({
                "kind": "complete",
                "result": result,
                "output": str(render_kwargs.get("output_file") or ""),
                "diagnostics_path": str(log_path),
            }, critical=True)
    except BaseException as exc:
        details = traceback.format_exc()
        emitter.send({
            "kind": "error",
            "phase": child_phase,
            "error_type": type(exc).__name__,
            "error": str(exc) or "<empty message>",
            "traceback": details,
            "diagnostics_path": str(log_path),
        }, critical=True)
    finally:
        if preview_session is not None:
            try:
                preview_session.stop("child_exit")
            except Exception:
                pass
        watchdog.close()
        cancel.close()
        if _child_handle_diagnostics_enabled():
            _write_diagnostic_line(
                log_path,
                f"[AMD CHILD HANDLE] phase=before_restore pid={os.getpid()} "
                f"stdout={_stream_snapshot('stdout', sys.stdout)} "
                f"stderr={_stream_snapshot('stderr', sys.stderr)} "
                f"fd1={_windows_fd_info(1)} fd2={_windows_fd_info(2)}",
            )
        if stdio_guard is not None:
            stdio_guard.restore()
        try:
            if log_file is not None:
                log_file.flush()
                log_file.close()
        except (OSError, ValueError):
            pass
        emitter.close()


def _kill_process_tree(pid: Optional[int]) -> None:
    if not pid:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3.0,
            )
        except Exception:
            pass


def run_amd_render_child(
    *,
    render_kwargs: dict[str, Any],
    preview_config: Optional[dict[str, Any]],
    progress_cb: Optional[Callable[[Any, Any], None]],
    on_render_progress: Optional[Callable[[Any, Any, Any, Any, Any], None]],
    on_preview_frame: Optional[Callable[[bytes, int, int], None]],
    cancel_event: Any,
    cancel_reason_provider: Optional[Callable[[], Any]],
    active_process_holder: dict[str, Any],
    generation_id: int,
) -> dict[str, Any]:
    """Run one AMD export in a fresh child and relay bounded state to GUI."""

    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=True)
    output = Path(str(render_kwargs.get("output_file") or "output.mp4"))
    diagnostics_path = output.parent / "scratch" / (
        f"amd_child_{int(generation_id)}_{int(time.time() * 1000)}.log"
    )
    inspect_render_job_pickle(render_kwargs)
    print(
        f"[AMD CHILD SPAWN] parent_pid={os.getpid()} generation={generation_id}",
        flush=True,
    )
    spawn_started_at = time.perf_counter()
    process = ctx.Process(
        target=_child_entry,
        args=(
            dict(render_kwargs), preview_config, child_conn,
            str(diagnostics_path), spawn_started_at, os.getpid(),
        ),
        name=f"TeleM-AMD-Render-{generation_id}",
    )
    process.start()
    child_conn.close()
    try:
        from src.process_lifecycle import RenderProcessRegistry
        RenderProcessRegistry.get_instance().register(process, proc_type="amd_child")
    except Exception:
        pass
    handle = AMDChildProcessHandle(process, parent_conn, diagnostics_path)
    active_process_holder["process"] = handle
    active_process_holder["child_pid"] = process.pid
    active_process_holder["child_generation_id"] = int(generation_id)
    active_process_holder["child_diagnostics_path"] = str(diagnostics_path)

    terminal: Optional[dict[str, Any]] = None
    cancel_sent_at: Optional[float] = None
    last_progress: dict[str, Any] = {}
    child_startup_ms: Optional[float] = None
    child_exit_seen_at: Optional[float] = None
    terminal_seen_at: Optional[float] = None
    lifecycle_error: Optional[str] = None
    reader_eof_logged = False
    reader = _ParentIpcReader(parent_conn)
    reader.start()
    try:
        while True:
            now = time.monotonic()
            child_alive = process.is_alive()
            if not child_alive and child_exit_seen_at is None:
                child_exit_seen_at = now
                print(
                    "[AMD CHILD LIFECYCLE] event=process_exit "
                    f"pid={process.pid} exitcode={process.exitcode} "
                    f"terminal={terminal.get('kind') if terminal else 'missing'}",
                    flush=True,
                )
            if reader.eof.is_set() and not reader_eof_logged:
                reader_eof_logged = True
                print(
                    "[AMD CHILD LIFECYCLE] event=ipc_eof "
                    f"pid={process.pid} error={reader.error or 'none'}",
                    flush=True,
                )

            if (
                terminal is None
                and cancel_event is not None
                and cancel_event.is_set()
                and cancel_sent_at is None
            ):
                reason = "INTERNAL_STOP"
                if cancel_reason_provider is not None:
                    try:
                        reason_value = cancel_reason_provider()
                        reason = getattr(reason_value, "value", str(reason_value))
                    except Exception:
                        pass
                handle.cancel(reason)
                cancel_sent_at = time.monotonic()

            try:
                message = reader.messages.get(timeout=0.1)
            except queue.Empty:
                message = None

            if message is None:
                now = time.monotonic()
                if cancel_sent_at is not None and now - cancel_sent_at > 15.0 and child_alive:
                    print("[AMD CHILD] cancel timeout; terminating process tree", flush=True)
                    _kill_process_tree(process.pid)
                    try:
                        process.join(timeout=2.0)
                    except Exception:
                        pass
                    lifecycle_error = "child did not exit within 15s of cancellation"
                    break
                if (
                    terminal_seen_at is not None
                    and child_alive
                    and now - terminal_seen_at > 10.0
                ):
                    lifecycle_error = (
                        "child sent terminal IPC but did not exit within 10s"
                    )
                    print(
                        "[AMD CHILD LIFECYCLE] event=terminal_exit_timeout "
                        f"pid={process.pid}",
                        flush=True,
                    )
                    _kill_process_tree(process.pid)
                    break
                if child_exit_seen_at is not None:
                    if reader.eof.is_set() and reader.messages.empty():
                        break
                    if now - child_exit_seen_at > 5.0:
                        lifecycle_error = (
                            "child exited but IPC did not reach EOF within 5s"
                        )
                        print(
                            "[AMD CHILD LIFECYCLE] event=post_exit_drain_timeout "
                            f"pid={process.pid} terminal="
                            f"{terminal.get('kind') if terminal else 'missing'}",
                            flush=True,
                        )
                        break
                continue
            if not isinstance(message, dict):
                continue
            kind = message.get("kind")
            if kind == "job_restored":
                child_startup_ms = float(message.get("startup_ms", 0.0) or 0.0)
                print(
                    "[AMD CHILD JOB RESTORED] "
                    f"generation={message.get('generation', generation_id)} "
                    f"child_pid={message.get('child_pid', process.pid)} "
                    f"startup_ms={child_startup_ms:.3f}",
                    flush=True,
                )
            elif kind == "progress_text":
                last_progress = dict(message)
                if progress_cb is not None:
                    progress_cb(message.get("value", 0), message.get("text", ""))
            elif kind == "progress":
                last_progress = dict(message)
                if on_render_progress is not None:
                    on_render_progress(
                        message.get("completed", 0),
                        message.get("total", 0),
                        message.get("elapsed", 0.0),
                        message.get("fps", 0.0),
                        message.get("hud_state", {}),
                    )
            elif kind == "preview":
                if on_preview_frame is not None:
                    on_preview_frame(
                        bytes(message.get("payload", b"")),
                        int(message.get("width", 0)),
                        int(message.get("height", 0)),
                    )
            elif kind == "warning":
                print(f"[AMD CHILD WARNING] {message.get('text', '')}", flush=True)
            elif kind in {"complete", "cancelled", "error"}:
                terminal = message
                terminal_seen_at = time.monotonic()
                print(
                    "[AMD CHILD LIFECYCLE] event=terminal_received "
                    f"pid={process.pid} kind={kind}",
                    flush=True,
                )
    finally:
        reader.close()
        try:
            process.join(timeout=3.0)
        except Exception:
            pass
        active_process_holder["process"] = None
        active_process_holder.pop("child_pid", None)
        active_process_holder.pop("child_generation_id", None)
        active_process_holder.pop("child_diagnostics_path", None)
        try:
            from src.process_lifecycle import RenderProcessRegistry
            RenderProcessRegistry.get_instance().unregister(process.pid)
        except Exception:
            pass

    if lifecycle_error is not None:
        tail = _tail(diagnostics_path)
        detail = (
            f"AMD child lifecycle error: {lifecycle_error}\n"
            f"[AMD CHILD STATE] pid={process.pid} exitcode={process.exitcode} "
            f"terminal={terminal.get('kind') if terminal else 'missing'} "
            f"last_progress={last_progress}"
        )
        if tail:
            detail += f"\n[AMD CHILD DIAGNOSTICS: {diagnostics_path}]\n{tail}"
        raise RuntimeError(detail)

    if (
        terminal is not None
        and terminal.get("kind") == "complete"
        and process.exitcode == 0
    ):
        if not output.exists() or output.stat().st_size <= 0:
            raise RuntimeError(
                "AMD child reported COMPLETE but final output is missing or empty"
            )
        if not _child_handle_diagnostics_enabled():
            try:
                diagnostics_path.unlink()
            except OSError:
                pass
        return {
            "child_pid": process.pid,
            "result": terminal.get("result"),
            "output": str(output),
            "child_exitcode": process.exitcode,
            "child_startup_ms": child_startup_ms,
        }
    if terminal is not None and terminal.get("kind") == "complete":
        raise RuntimeError(
            "AMD child reported COMPLETE but exited with "
            f"code {process.exitcode} (pid={process.pid})"
        )
    if terminal is not None and terminal.get("kind") == "cancelled":
        try:
            diagnostics_path.unlink()
        except OSError:
            pass
        return {
            "cancelled": True,
            "reason": terminal.get("reason", "INTERNAL_STOP"),
            "child_pid": process.pid,
            "child_exitcode": process.exitcode,
            "child_startup_ms": child_startup_ms,
        }

    tail = _tail(diagnostics_path)
    if terminal is not None and terminal.get("kind") == "error":
        message = (
            f"{terminal.get('error_type', 'RuntimeError')}: "
            f"{terminal.get('error', '<empty message>')}"
        )
        trace = terminal.get("traceback") or ""
        phase = terminal.get("phase")
        if phase:
            message = f"{message} (phase={phase})"
    else:
        message = (
            f"AMD child exited without terminal result (exitcode={process.exitcode})"
        )
        trace = ""
    detail = f"{message}\n{trace}".strip()
    detail += (
        f"\n[AMD CHILD STATE] pid={process.pid} exitcode={process.exitcode}"
        f" last_progress={last_progress}"
    )
    if tail:
        detail += f"\n[AMD CHILD DIAGNOSTICS: {diagnostics_path}]\n{tail}"
    raise RuntimeError(detail)
