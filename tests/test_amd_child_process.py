from __future__ import annotations

import multiprocessing as mp
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import threading
import time

import numpy as np

from src.ffmpeg.amd_child_process import (
    AMDChildProcessHandle,
    _ChildStdioRedirect,
    _ChildIpcEmitter,
    _ParentIpcReader,
    inspect_render_job_pickle,
    run_amd_render_child,
)


def _stdio_matrix_child(conn, log_path, mode):
    """Spawn target for the Windows stdio/finalization regression matrix."""
    if mode == "none":
        sys.stderr = None
    elif mode == "closed":
        try:
            sys.stderr.close()
        except Exception:
            pass
    log_file = Path(log_path).open("w", encoding="utf-8", buffering=1)
    guard = _ChildStdioRedirect(log_file)
    try:
        guard.redirect()
        print(f"stdio probe mode={mode}", flush=True)
        conn.send({
            "kind": "success",
            "stderr_usable": bool(sys.stderr is not None and not sys.stderr.closed),
        })
    except BaseException as exc:
        conn.send({"kind": "error", "error": repr(exc)})
    finally:
        guard.restore()
        log_file.close()
        conn.close()
from src.ffmpeg.amd_hevc_preview import AMDGPUNativeFrameTapPreview
from src.telemetry_processed_cache import LazySampleList


def test_child_ipc_preview_is_latest_only_and_control_is_reliable():
    parent, child = mp.get_context("spawn").Pipe(duplex=True)
    emitter = _ChildIpcEmitter(child)
    emitter.start()
    try:
        emitter.preview(b"old", 2, 2)
        emitter.preview(b"new", 2, 2)
        emitter.send({"kind": "complete", "output": "out.mp4"}, critical=True)

        messages = []
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(messages) < 2:
            if parent.poll(0.05):
                messages.append(parent.recv())
        assert any(m.get("kind") == "complete" for m in messages)
        previews = [m for m in messages if m.get("kind") == "preview"]
        assert len(previews) == 1
        assert previews[0]["payload"] == b"new"
    finally:
        emitter.close()
        parent.close()


def test_child_process_handle_exposes_popen_lifecycle():
    process = mp.get_context("spawn").Process(target=time.sleep, args=(0.05,))
    parent, child = mp.get_context("spawn").Pipe(duplex=True)
    process.start()
    child.close()
    handle = AMDChildProcessHandle(process, parent, "scratch/test-child.log")
    assert handle.pid == process.pid
    assert handle.poll() is None
    process.join(timeout=2.0)
    assert handle.poll() == 0
    parent.close()


def test_spawn_stdio_finalization_matrix_has_no_exitcode_120(tmp_path):
    """Normal, redirected, None and closed stderr all exit cleanly."""
    ctx = mp.get_context("spawn")
    for mode in ("normal", "file", "none", "closed"):
        parent, child = ctx.Pipe(duplex=True)
        process = ctx.Process(
            target=_stdio_matrix_child,
            args=(child, str(tmp_path / f"stdio-{mode}.log"), mode),
        )
        process.start()
        child.close()
        try:
            assert parent.poll(5.0), f"stdio probe did not report: {mode}"
            message = parent.recv()
            assert message["kind"] == "success", message
            assert message["stderr_usable"]
        finally:
            parent.close()
            process.join(timeout=5.0)
        assert not process.is_alive()
        assert process.exitcode == 0, (mode, process.exitcode)
        assert (tmp_path / f"stdio-{mode}.log").read_text(encoding="utf-8")


def test_parent_ipc_reader_delivers_terminal_then_observes_eof():
    parent, child = mp.get_context("spawn").Pipe(duplex=True)
    reader = _ParentIpcReader(parent)
    reader.start()
    try:
        child.send({"kind": "complete", "result": 30})
        child.close()

        assert reader.messages.get(timeout=2.0) == {
            "kind": "complete", "result": 30
        }
        assert reader.eof.wait(timeout=2.0)
    finally:
        reader.close()


def test_parent_ipc_reader_observes_eof_without_terminal_message():
    parent, child = mp.get_context("spawn").Pipe(duplex=True)
    reader = _ParentIpcReader(parent)
    reader.start()
    try:
        child.close()

        assert reader.eof.wait(timeout=2.0)
        assert reader.messages.empty()
    finally:
        reader.close()


def test_external_preview_frame_updates_gui_session_without_native_handle():
    frames = []
    preview = AMDGPUNativeFrameTapPreview(
        width=4, height=2, on_frame=lambda raw, w, h: frames.append((raw, w, h))
    )
    assert preview.start()
    preview.accept_external_frame(b"frame", 4, 2)
    assert frames == [(b"frame", 4, 2)]
    assert preview.stats()["updates"] == 1
    preview.stop("test")


def test_render_job_pickle_diagnostics_are_data_only_and_non_materializing():
    timestamp = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
    samples = LazySampleList(
        np.array([[timestamp, 1.0], [timestamp + 1.0, 2.0]]),
        is_vector=False,
        tz_aware=True,
    )
    render_job = {
        "input_files": [r"D:\GoPro\2026-09-01\GX010244.MP4"],
        "field_samples": {"accel_x_samples": samples},
        "layout": {"indicators": {}},
        "generation_id": 17,
    }

    diagnostics = inspect_render_job_pickle(render_job)

    assert diagnostics["pickle_size"] > 0
    assert diagnostics["pickle_time_ms"] >= 0.0
    assert diagnostics["top_level_types"]["field_samples"] == "builtins.dict"
    assert diagnostics["lazy_sample_lists"] == [{
        "path": "render_job.field_samples.accel_x_samples",
        "state": "lazy",
        "count": 2,
        "array_bytes": 32,
    }]
    assert samples._materialized is False


def test_child_error_is_contained_and_next_spawn_is_allowed(tmp_path):
    child_pids = []
    for generation in (901, 902):
        holder = {}
        try:
            run_amd_render_child(
                render_kwargs={
                    "generation_id": generation,
                    "output_file": tmp_path / f"never-created-{generation}.mp4",
                    "unexpected_render_argument": True,
                },
                preview_config=None,
                progress_cb=None,
                on_render_progress=None,
                on_preview_frame=None,
                cancel_event=threading.Event(),
                cancel_reason_provider=None,
                active_process_holder=holder,
                generation_id=generation,
            )
        except RuntimeError as exc:
            error_text = str(exc)
            assert "unexpected_render_argument" in error_text
            assert "phase=render" in error_text
            match = re.search(r"\[AMD CHILD STATE\] pid=(\d+)", error_text)
            assert match is not None
            child_pids.append(int(match.group(1)))
        else:
            raise AssertionError("controlled child error was not relayed")
        assert holder.get("process") is None
        assert "child_pid" not in holder

    active_pids = {process.pid for process in mp.active_children()}
    assert all(pid not in active_pids for pid in child_pids if pid is not None)


def test_child_bootstrap_exception_is_relayed_via_ipc(tmp_path, monkeypatch):
    monkeypatch.setenv("AMD_CHILD_HANDLE_DIAGNOSTICS", "1")
    holder = {}
    try:
        run_amd_render_child(
            render_kwargs={
                "generation_id": "not-an-integer",
                "output_file": tmp_path / "never-created-bootstrap.mp4",
            },
            preview_config=None,
            progress_cb=None,
            on_render_progress=None,
            on_preview_frame=None,
            cancel_event=threading.Event(),
            cancel_reason_provider=None,
            active_process_holder=holder,
            generation_id=903,
        )
    except RuntimeError as exc:
        error_text = str(exc)
        assert "ValueError" in error_text
        assert "phase=bootstrap/startup" in error_text
        assert "invalid literal" in error_text
    else:
        raise AssertionError("bootstrap exception was not relayed")
    assert holder.get("process") is None
    logs = list((tmp_path / "scratch").glob("amd_child_*.log"))
    assert logs
    diagnostic_text = logs[0].read_text(encoding="utf-8")
    assert "phase=entry" in diagnostic_text
    assert "phase=before_restore" in diagnostic_text
    assert "fd1=" in diagnostic_text and "fd2=" in diagnostic_text
