from __future__ import annotations

import errno
import json
import shutil
from types import SimpleNamespace

from src.ffmpeg.render_errors import (
    DecoderError,
    EncoderError,
    GpuError,
    MuxError,
    RuntimeStorageMonitor,
    SourceReadError,
    StorageError,
    check_preflight_storage,
    classify_mux_error,
    coerce_render_error,
)


def test_io_exception_codes_and_scope_are_preserved(tmp_path):
    cases = [
        (OSError(errno.ENOSPC, "full"), "ENOSPC", StorageError, True),
        (PermissionError(errno.EACCES, "denied"), "EACCES", StorageError, True),
        (FileNotFoundError(errno.ENOENT, "missing"), "ENOENT", SourceReadError, False),
        (BrokenPipeError(errno.EPIPE, "pipe closed"), "EPIPE", MuxError, False),
    ]
    for exc, code, error_type, pauses in cases:
        error = coerce_render_error(
            exc,
            job_id="job-a",
            stage="live_mux",
            source_path="input.mp4",
            output_path=str(tmp_path / "out.mp4"),
        )
        assert isinstance(error, error_type)
        assert error.code == code
        assert error.pause_queue is pauses
        assert error.job_id == "job-a"
        assert error.stage == "live_mux"


def test_missing_output_directory_is_a_queue_blocker_without_creation(tmp_path):
    output = tmp_path / "missing" / "out.mp4"
    ok, error = check_preflight_storage(output, 10.0, 1_000_000)
    assert not ok
    assert isinstance(error, StorageError)
    assert error.code == "ENOENT"
    assert error.pause_queue is True
    assert not output.parent.exists()


def test_runtime_storage_monitor_fault_injection_pauses_write(tmp_path, monkeypatch):
    output = tmp_path / "out.mp4"
    callbacks = []
    monitor = RuntimeStorageMonitor(
        output,
        finalization_reserve_bytes=100,
        on_low_space_callback=lambda free, reserve: callbacks.append((free, reserve)),
    )
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: SimpleNamespace(free=0, total=1000, used=1000))
    monitor._monitor_loop()
    assert monitor.stop_requested_low_space.is_set()
    assert monitor.last_error.errno == errno.ENOSPC
    assert callbacks == [(0, 100 * 1024 * 1024)]


def test_ffmpeg_failures_keep_subsystem_category():
    errors = [
        classify_mux_error(1, "No space left on device"),
        classify_mux_error(1, "Error while decoding stream"),
        classify_mux_error(1, "D3D device removed"),
        classify_mux_error(1, "Error initializing NVENC encoder"),
        classify_mux_error(1, "Could not write trailer to output MP4"),
    ]
    assert isinstance(errors[0], StorageError)
    assert isinstance(errors[1], DecoderError)
    assert isinstance(errors[2], GpuError)
    assert isinstance(errors[3], EncoderError)
    assert isinstance(errors[4], MuxError)
    restored = json.loads(json.dumps(errors[0].to_dict()))
    assert restored["code"] == "ENOSPC"
    assert restored["stage"] == "render"
