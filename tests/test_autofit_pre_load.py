"""Tests for AutoFIT visible before 'Load' (Problem 3 regression).

Verifies:
1. AutoFIT automatically populates the FIT/GPX field in the GUI when MP4 is selected,
   BEFORE clicking 'Wczytaj' (Load).
2. Stale scans from previous requests are rejected via request generation id (_autofit_gen).
3. User's manual selection is never overwritten by an asynchronous AutoFIT result.
4. Clear button cleanly resets paths and generation.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication
from src.gui.qt.signals import get_signals
from src.gui.qt.tabs.load_tab import LoadTab
from src.integrations.activity_provider import ActivityCandidate


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_autofit_pre_load_auto_populates_ui(qapp, tmp_path):
    """Verify selecting MP4 triggers AutoFIT background search and updates btn_telemetry
    before clicking 'Wczytaj'.
    """
    tab = LoadTab()
    
    video_path = tmp_path / "sample.mp4"
    dummy_fit = tmp_path / "sample.fit"
    video_path.write_bytes(b"synthetic video")
    dummy_fit.write_bytes(b"synthetic fit")
    
    from datetime import datetime
    dt0 = datetime(2026, 9, 1, 10, 0, 0)
    dt1 = datetime(2026, 9, 1, 10, 10, 0)
    
    with patch("src.multifile.probe_clip_time_interval", return_value=(dt0, dt1, 600.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_fit_time_range",
               return_value=(dt0, dt1, 600.0)):
        
        # Simulating user picking MP4
        tab._video_paths = [str(video_path)]
        tab._autofit_gen += 1
        tab._try_auto_fit_search([str(video_path)], gen=tab._autofit_gen)
        
        # Wait for thread and QTimer.singleShot(0, ...)
        deadline = time.time() + 2.0
        while time.time() < deadline and not tab._fit_path:
            qapp.processEvents()
            time.sleep(0.01)
            
        qapp.processEvents()
        
        assert tab._fit_path == str(dummy_fit)
        assert tab.btn_telemetry.text() == f"{dummy_fit.name} ✓"
        assert tab.btn_telemetry.toolTip() == str(dummy_fit)


def test_autofit_stale_generation_rejected(qapp):
    """Verify stale scan (from a superseded MP4 selection) is ignored."""
    tab = LoadTab()
    
    dummy_mp4_1 = "C:/Videos/old.mp4"
    dummy_fit_1 = Path("C:/Videos/old.fit")
    
    dummy_mp4_2 = "C:/Videos/new.mp4"
    dummy_fit_2 = Path("C:/Videos/new.fit")
    
    from datetime import datetime
    dt0 = datetime(2026, 9, 1, 10, 0, 0)
    dt1 = datetime(2026, 9, 1, 10, 10, 0)
    
    with patch("src.multifile.probe_clip_time_interval", return_value=(dt0, dt1, 600.0, "exact")), \
         patch("telemetry_fit.find_best_fit_match", side_effect=[(dummy_fit_1, ""), (dummy_fit_2, "")]):
        
        # User selects clip 1
        tab._video_paths = [dummy_mp4_1]
        tab._autofit_gen += 1
        old_gen = tab._autofit_gen
        
        # User immediately changes to clip 2
        tab._video_paths = [dummy_mp4_2]
        tab._autofit_gen += 1
        new_gen = tab._autofit_gen
        
        # Run stale search with old_gen
        tab._try_auto_fit_search([dummy_mp4_1], gen=old_gen)
        
        deadline = time.time() + 0.5
        while time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
            
        # Stale search must NOT have set _fit_path
        assert tab._fit_path != str(dummy_fit_1)
        assert tab.btn_telemetry.text() != str(dummy_fit_1)


def test_autofit_user_manual_selection_preserved(qapp):
    """Verify manual FIT selection is never overwritten by AutoFIT."""
    tab = LoadTab()
    
    manual_fit = "C:/Manual/my_custom.fit"
    tab._user_selected_telemetry = True
    tab._fit_path = manual_fit
    tab.btn_telemetry.setText(manual_fit)
    
    dummy_mp4 = "C:/Videos/sample.mp4"
    dummy_fit = Path("C:/Videos/auto.fit")
    
    from datetime import datetime
    dt0 = datetime(2026, 9, 1, 10, 0, 0)
    dt1 = datetime(2026, 9, 1, 10, 10, 0)
    
    with patch("src.multifile.probe_clip_time_interval", return_value=(dt0, dt1, 600.0, "exact")), \
         patch("telemetry_fit.find_best_fit_match", return_value=(dummy_fit, "")):
        
        tab._video_paths = [dummy_mp4]
        tab._autofit_gen += 1
        tab._try_auto_fit_search([dummy_mp4], gen=tab._autofit_gen)
        
        deadline = time.time() + 0.5
        while time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
            
        # Manual selection must remain intact
        assert tab._fit_path == manual_fit
        assert tab.btn_telemetry.text() == manual_fit


def test_autofit_clear_resets_state(qapp):
    """Verify _on_clear resets all paths, button text, and increments generation."""
    tab = LoadTab()
    
    tab._video_paths = ["C:/Videos/sample.mp4"]
    tab._fit_path = "C:/Videos/sample.fit"
    tab._user_selected_telemetry = True
    tab.btn_telemetry.setText("C:/Videos/sample.fit")
    initial_gen = tab._autofit_gen
    
    tab._on_clear()
    
    assert tab._video_paths == []
    assert tab._fit_path == ""
    assert tab._gpx_path == ""
    assert not tab._user_selected_telemetry
    assert tab._autofit_gen > initial_gen
    assert "Wybierz FIT/GPX" in tab.btn_telemetry.text()


def test_activity_selection_round_trips_from_worker_to_gui(qapp):
    """The existing chooser returns a Python candidate safely across Qt threads."""
    from datetime import datetime, timezone
    from PySide6.QtWidgets import QInputDialog

    tab = LoadTab()
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    candidates = [
        ActivityCandidate(str(i), "local", f"ride {i}", "FIT", now,
                          now + timedelta(minutes=10), 600.0)
        for i in (1, 2)
    ]
    cancel_event = threading.Event()
    result = {}
    with patch.object(QInputDialog, "getItem", side_effect=lambda *args: (args[3][1], True)):
        worker = threading.Thread(
            target=lambda: result.setdefault(
            "candidate", tab._request_activity_selection(
                [(candidate, 0.8) for candidate in candidates], tab._autofit_gen, cancel_event,
            ),
            ),
        )
        worker.start()
        deadline = time.time() + 2.0
        while worker.is_alive() and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        worker.join(timeout=0.1)

    assert not worker.is_alive()
    assert result.get("candidate") is candidates[1]
    tab.close()
