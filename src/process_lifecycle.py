"""Central process lifecycle and Windows Job Object management.

Provides guaranteed termination of worker processes, child processes, and FFmpeg
subprocesses on cancellation, GUI close, exception, and parent crash/force-close.
"""

from __future__ import annotations

import os
import sys
import time
import threading
import subprocess
from typing import Any, Optional

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Function prototypes with explicit 64-bit handle types
    CreateJobObjectW = kernel32.CreateJobObjectW
    CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    CreateJobObjectW.restype = wintypes.HANDLE

    SetInformationJobObject = kernel32.SetInformationJobObject
    SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    SetInformationJobObject.restype = wintypes.BOOL

    AssignProcessToJobObject = kernel32.AssignProcessToJobObject
    AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    AssignProcessToJobObject.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    GetCurrentProcess = kernel32.GetCurrentProcess
    GetCurrentProcess.argtypes = []
    GetCurrentProcess.restype = wintypes.HANDLE

    OpenProcess = kernel32.OpenProcess
    OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    OpenProcess.restype = wintypes.HANDLE

    IsProcessInJob = kernel32.IsProcessInJob
    IsProcessInJob.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.BOOL),
    ]
    IsProcessInJob.restype = wintypes.BOOL

    TerminateProcess = kernel32.TerminateProcess
    TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    TerminateProcess.restype = wintypes.BOOL

    WaitForSingleObject = kernel32.WaitForSingleObject
    WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    WaitForSingleObject.restype = wintypes.DWORD

    # Constants
    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    PROCESS_TERMINATE = 0x0001
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000

    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryLimit", ctypes.c_size_t),
            ("PeakJobMemoryLimit", ctypes.c_size_t),
        ]


class RenderJobGuard:
    """Manages a Windows Job Object configured with KILL_ON_JOB_CLOSE."""

    _instance: Optional[RenderJobGuard] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> RenderJobGuard:
        with cls._lock:
            if cls._instance is None:
                cls._instance = RenderJobGuard()
            return cls._instance

    def __init__(self) -> None:
        self.job_handle: Any = None
        self.parent_assigned: bool = False
        self._closed: bool = False

        if not _IS_WINDOWS:
            return

        try:
            h_job = CreateJobObjectW(None, None)
            if not h_job:
                err = ctypes.get_last_error()
                print(f"[PROC] ERROR: CreateJobObjectW failed with error={err}", flush=True)
                return

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            success = SetInformationJobObject(
                h_job,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not success:
                err = ctypes.get_last_error()
                print(f"[PROC] ERROR: SetInformationJobObject failed with error={err}", flush=True)
                CloseHandle(h_job)
                return

            self.job_handle = h_job
            print(f"[PROC] job created handle={h_job}", flush=True)

            # Check if parent is already in a job, and attempt to assign parent
            h_cur = GetCurrentProcess()
            in_any_job = wintypes.BOOL(False)
            IsProcessInJob(h_cur, None, ctypes.byref(in_any_job))

            assign_ret = AssignProcessToJobObject(self.job_handle, h_cur)
            if assign_ret:
                self.parent_assigned = True
                print(
                    f"[PROC] assigned TeleM parent pid={os.getpid()} to job (in_prior_job={bool(in_any_job.value)})",
                    flush=True,
                )
            else:
                err = ctypes.get_last_error()
                print(
                    f"[PROC] parent pid={os.getpid()} could not be assigned to job (err={err}, in_prior_job={bool(in_any_job.value)}); relying on explicit child assignment",
                    flush=True,
                )
        except Exception as exc:
            print(f"[PROC] ERROR initializing RenderJobGuard: {exc}", flush=True)

    def assign_process(self, proc_or_pid: Any) -> bool:
        """Assign an external or child process to this Job Object."""
        if not _IS_WINDOWS or not self.job_handle or self._closed:
            return False

        pid = getattr(proc_or_pid, "pid", None)
        if pid is None:
            if isinstance(proc_or_pid, int):
                pid = proc_or_pid
            else:
                return False

        h_proc = None
        try:
            # Need SET_QUOTA | TERMINATE to assign, plus QUERY_LIMITED_INFORMATION to test IsProcessInJob
            desired_access = (
                PROCESS_SET_QUOTA
                | PROCESS_TERMINATE
                | PROCESS_QUERY_LIMITED_INFORMATION
                | SYNCHRONIZE
            )
            h_proc = OpenProcess(desired_access, False, int(pid))
            if not h_proc:
                err = ctypes.get_last_error()
                print(f"[PROC] OpenProcess failed for pid={pid} error={err}", flush=True)
                return False

            # Check if already in this job
            in_this_job = wintypes.BOOL(False)
            if (
                IsProcessInJob(h_proc, self.job_handle, ctypes.byref(in_this_job))
                and in_this_job.value
            ):
                print(f"[PROC] assigned pid={pid} (already in job via inheritance)", flush=True)
                return True

            ret = AssignProcessToJobObject(self.job_handle, h_proc)
            if ret:
                print(f"[PROC] assigned pid={pid}", flush=True)
                return True
            else:
                err = ctypes.get_last_error()
                # If error is ACCESS_DENIED (5), check again if child is actually in job
                in_job_check = wintypes.BOOL(False)
                if (
                    IsProcessInJob(h_proc, self.job_handle, ctypes.byref(in_job_check))
                    and in_job_check.value
                ):
                    print(f"[PROC] assigned pid={pid} (verified in job despite assign rc=0)", flush=True)
                    return True
                print(f"[PROC] ERROR: AssignProcessToJobObject failed for pid={pid} error={err}", flush=True)
                return False
        except Exception as exc:
            print(f"[PROC] ERROR assigning pid={pid} to job: {exc}", flush=True)
            return False
        finally:
            if h_proc:
                CloseHandle(h_proc)

    def close(self) -> None:
        """Close the job handle.

        WARNING:
        If the current process is assigned to this Job Object and
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE is active, explicitly closing
        the last handle terminates the current process as well.
        Do not call from normal GUI shutdown.
        """
        with self._lock:
            if self._closed or not self.job_handle:
                return
            self._closed = True
            h = self.job_handle
            self.job_handle = None
            try:
                print(f"[PROC] job closed handle={h}", flush=True)
                CloseHandle(h)
            except Exception as exc:
                print(f"[PROC] ERROR closing job handle: {exc}", flush=True)


class RenderProcessRegistry:
    """Thread-safe registry of all active worker, child, and FFmpeg processes."""

    _instance: Optional[RenderProcessRegistry] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> RenderProcessRegistry:
        with cls._lock:
            if cls._instance is None:
                cls._instance = RenderProcessRegistry()
            return cls._instance

    def __init__(self) -> None:
        self._entries: dict[int, dict[str, Any]] = {}
        self._mutex = threading.Lock()
        self._job_guard = RenderJobGuard.get_instance()

    def register(self, proc_or_pid: Any, proc_type: str = "worker") -> Optional[int]:
        """Register a process and ensure it belongs to the Render Job Object."""
        pid = getattr(proc_or_pid, "pid", None)
        if pid is None:
            if isinstance(proc_or_pid, int):
                pid = proc_or_pid
            else:
                return None

        pid = int(pid)
        with self._mutex:
            self._entries[pid] = {
                "proc": proc_or_pid,
                "type": proc_type,
                "created_at": time.time(),
            }

        # Assign to Job Object
        self._job_guard.assign_process(pid)
        return pid

    def unregister(self, proc_or_pid: Any) -> None:
        """Unregister a process after normal exit."""
        pid = getattr(proc_or_pid, "pid", None)
        if pid is None:
            if isinstance(proc_or_pid, int):
                pid = proc_or_pid
            else:
                return

        pid = int(pid)
        with self._mutex:
            self._entries.pop(pid, None)
            if not self._entries:
                print("[PROC] registry empty", flush=True)

    def get_active_pids(self) -> list[int]:
        """Return list of currently registered PIDs."""
        with self._mutex:
            return list(self._entries.keys())

    def terminate_all_render_children(self, timeout: float = 2.0) -> None:
        """Central bounded termination for all registered render children.

        Follows:
          terminate -> join/wait bounded -> kill if still alive -> join/wait bounded
        """
        with self._mutex:
            active_items = list(self._entries.items())

        if not active_items:
            return

        print(
            f"[PROC] cancel requested: terminating {len(active_items)} registered children",
            flush=True,
        )

        # 1. Initiate terminate for each process
        for pid, entry in active_items:
            proc = entry.get("proc")
            proc_type = entry.get("type", "worker")
            print(f"[PROC] terminate pid={pid} type={proc_type}", flush=True)

            try:
                if hasattr(proc, "terminate") and callable(proc.terminate):
                    proc.terminate()
                elif _IS_WINDOWS:
                    h = OpenProcess(PROCESS_TERMINATE, False, pid)
                    if h:
                        try:
                            TerminateProcess(h, 1)
                        finally:
                            CloseHandle(h)
            except Exception as exc:
                print(f"[PROC] terminate pid={pid} error: {exc}", flush=True)

        # 2. Bounded wait for processes to exit
        deadline = time.monotonic() + max(0.2, timeout * 0.6)
        remaining = list(active_items)

        while remaining and time.monotonic() < deadline:
            still_running = []
            for pid, entry in remaining:
                if not self._is_process_alive(pid, entry.get("proc")):
                    print(f"[PROC] pid={pid} exited cleanly after terminate", flush=True)
                else:
                    still_running.append((pid, entry))
            remaining = still_running
            if remaining:
                time.sleep(0.05)

        # 3. Kill any remaining processes
        if remaining:
            print(f"[PROC] {len(remaining)} processes still alive; issuing kill", flush=True)
            for pid, entry in remaining:
                proc = entry.get("proc")
                proc_type = entry.get("type", "worker")
                print(f"[PROC] kill pid={pid} type={proc_type}", flush=True)
                try:
                    if hasattr(proc, "kill") and callable(proc.kill):
                        proc.kill()
                    elif _IS_WINDOWS:
                        h = OpenProcess(PROCESS_TERMINATE, False, pid)
                        if h:
                            try:
                                TerminateProcess(h, 9)
                            finally:
                                CloseHandle(h)
                except Exception as exc:
                    print(f"[PROC] kill pid={pid} error: {exc}", flush=True)

            # Bounded wait after kill
            kill_deadline = time.monotonic() + max(0.2, timeout * 0.4)
            while remaining and time.monotonic() < kill_deadline:
                remaining = [
                    (pid, e)
                    for pid, e in remaining
                    if self._is_process_alive(pid, e.get("proc"))
                ]
                if remaining:
                    time.sleep(0.05)

        # Clear entries
        with self._mutex:
            for pid, _ in active_items:
                self._entries.pop(pid, None)
            if not self._entries:
                print("[PROC] registry empty", flush=True)

    @staticmethod
    def _is_process_alive(pid: int, proc: Any) -> bool:
        """Check if a process is still running."""
        try:
            if hasattr(proc, "is_alive") and callable(proc.is_alive):
                return bool(proc.is_alive())
            if hasattr(proc, "poll") and callable(proc.poll):
                return proc.poll() is None
            if _IS_WINDOWS:
                h = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not h:
                    return False
                try:
                    res = WaitForSingleObject(h, 0)
                    return res == WAIT_TIMEOUT
                finally:
                    CloseHandle(h)
            return True
        except Exception:
            return False
