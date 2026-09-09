"""Contracts for the AMD export-preview isolation audit."""
from __future__ import annotations

import sys
import threading
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.widgets.video_preview import VideoPreview


def test_preview_background_keeps_only_latest_request():
    app = QApplication.instance() or QApplication(sys.argv)
    tab = RenderTab(preview=VideoPreview())
    tab._controller = object()
    tab._rendering = True
    tab._cancelling = False
    tab._export_preview_native = False
    tab._preview_is_foreground = lambda: True
    calls: list[float] = []
    original = tab._build_preview_qimage

    def slow_build(ts: float, _tw: int, _th: int):
        calls.append(ts)
        time.sleep(0.05)
        return QImage(2, 2, QImage.Format_RGBA8888)

    tab._build_preview_qimage = slow_build
    tab._trigger_async_preview(1.0)
    time.sleep(0.01)
    tab._trigger_async_preview(2.0)
    tab._trigger_async_preview(3.0)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with tab._preview_lock:
            active = tab._preview_worker_active
        if not active:
            break
        time.sleep(0.01)
    # Scheduling may coalesce the first request before the worker starts;
    # latest-state semantics only require that the newest request wins.
    assert calls[-1] == 3.0
    assert len(calls) <= 2
    with tab._preview_lock:
        assert not tab._preview_worker_active
        assert tab._preview_pending_ts is None
    tab._rendering = False
    tab._build_preview_qimage = original


def test_preview_background_does_not_start_worker():
    app = QApplication.instance() or QApplication(sys.argv)
    tab = RenderTab(preview=VideoPreview())
    tab._controller = object()
    tab._rendering = True
    tab._cancelling = False
    tab._preview_is_foreground = lambda: False
    calls = []
    tab._build_preview_qimage = lambda *_args: calls.append(True)
    tab._trigger_async_preview(42.0)
    time.sleep(0.05)
    assert calls == []
    with tab._preview_lock:
        assert not tab._preview_worker_active
        assert tab._preview_pending_ts == 42.0
    tab._rendering = False


def test_preview_fault_isolated_from_final_render(monkeypatch, capsys):
    app = QApplication.instance() or QApplication(sys.argv)
    tab = RenderTab(preview=VideoPreview())

    class Controller:
        render_cancel_event = threading.Event()
        layout = {"width": 1920, "height": 1080}

    controller = Controller()
    tab._controller = controller
    tab._rendering = True
    tab._cancelling = False
    tab._render_generation_id = 77
    tab._preview_is_foreground = lambda: True
    tab._preview_stop_event = threading.Event()
    monkeypatch.setenv("TELEM_EXPORT_PREVIEW_FAULT_INJECTION", "1")

    tab._trigger_async_preview(12.5)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with tab._preview_lock:
            active = tab._preview_worker_active
        if not active:
            break
        time.sleep(0.01)

    log = capsys.readouterr().out
    assert "[EXPORT PREVIEW ERROR]" in log
    assert "generation=77" in log
    assert "timestamp=12.500000" in log
    assert "stage=preview_worker" in log
    assert "exception_type=RuntimeError" in log
    assert "exception=preview fault injection" in log
    assert "traceback=Traceback" in log
    assert tab._preview_failed
    assert tab._preview_stop_event.is_set()
    assert tab._rendering
    assert not tab._cancelling
    assert not controller.render_cancel_event.is_set()
    app.processEvents()
