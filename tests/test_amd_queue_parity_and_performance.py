"""Unit tests for AMD Queue vs Direct parity, double signal fix, and UI optimization."""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.gui.export_queue import ExportJob, ExportQueue
from src.gui.map_prefetch import MapBackgroundPrefetchManager


def test_single_canonical_notification_no_double_signal(tmp_path):
    """Confirm that _notify_updated emits exactly once through the canonical path."""
    signals_mock = MagicMock()
    callback_mock = MagicMock()

    q = ExportQueue(signals=signals_mock, appdata_dir=tmp_path)
    q.set_on_job_updated(callback_mock)

    job = ExportJob(
        video_paths=["test.mp4"],
        output_path="out.mp4",
    )
    q.add_job(job)

    # Reset call counts
    signals_mock.sig_queue_job_updated.emit.reset_mock()
    callback_mock.reset_mock()

    # Trigger notify_render_progress
    q.notify_render_progress(job.job_id, 0.25, phase="render")

    # Canonical path with signals present should emit sig_queue_job_updated ONCE and NOT call callback
    assert signals_mock.sig_queue_job_updated.emit.call_count == 1
    assert callback_mock.call_count == 0


def test_telem_queue_progress_ui_ab_switch(tmp_path, monkeypatch):
    """Confirm TELEM_QUEUE_PROGRESS_UI=0 suppresses per-frame signal emission without percent change."""
    signals_mock = MagicMock()
    q = ExportQueue(signals=signals_mock, appdata_dir=tmp_path)

    job = ExportJob(
        video_paths=["test.mp4"],
        output_path="out.mp4",
    )
    q.add_job(job)

    monkeypatch.setenv("TELEM_QUEUE_PROGRESS_UI", "0")
    signals_mock.sig_queue_job_updated.emit.reset_mock()

    # Two updates within the same percent (e.g. 0.101 and 0.102 -> both 10%)
    q.notify_render_progress(job.job_id, 0.101, phase="render")
    assert signals_mock.sig_queue_job_updated.emit.call_count == 1  # 0% -> 10% changed

    signals_mock.sig_queue_job_updated.emit.reset_mock()
    q.notify_render_progress(job.job_id, 0.102, phase="render")
    # Same integer percent: suppressed!
    assert signals_mock.sig_queue_job_updated.emit.call_count == 0

    # Moving to 11% should emit
    q.notify_render_progress(job.job_id, 0.110, phase="render")
    assert signals_mock.sig_queue_job_updated.emit.call_count == 1


def test_map_prefetch_pause_or_cancel_bounded_join():
    """Confirm pause_or_cancel_for_render sets cancel and joins worker thread."""
    mgr = MapBackgroundPrefetchManager.get_instance()
    mgr.cancel_current("test_clean")

    # Status before render should report not alive after pause_or_cancel
    res = mgr.pause_or_cancel_for_render(timeout=1.0)
    assert not res.get("alive_after", False)
    assert mgr._active_job is None
    assert not mgr.is_active()


def test_queue_diagnostic_counters(tmp_path):
    """Verify ExportQueue counters track updates and can be reset."""
    ExportQueue.reset_queue_diagnostic_counters()
    assert ExportQueue.get_queue_progress_update_count() == 0

    q = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(video_paths=["test.mp4"], output_path="out.mp4")
    q.add_job(job)

    for i in range(10):
        q.notify_render_progress(job.job_id, i * 0.1, phase="render")

    assert ExportQueue.get_queue_progress_update_count() == 10
    ExportQueue.reset_queue_diagnostic_counters()
    assert ExportQueue.get_queue_progress_update_count() == 0
