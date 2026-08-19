"""Testy przebudowanej zakładki Rendering.

Weryfikują:
- współdzielenie JEDNEJ instancji VideoPreview między zakładkami Projekt i Rendering,
- przenoszenie podglądu przy zmianie zakładki (bez duplikacji backendu),
- mechanizm zakresu eksportu IN/OUT (graniczne cut_regions, re-use CutMixin),
- zachowanie istniejących opcji eksportu (nazwy atrybutów).
"""

from __future__ import annotations

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication

from src.gui.qt.signals import get_signals
from src.gui.qt._mixins.cut_mixin import CutMixin
from src.gui.qt.widgets.video_preview import VideoPreview


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class MockController(CutMixin):
    """Minimalny kontroler z REALNYM CutMixin (ta sama logika co AppController)."""

    def __init__(self) -> None:
        self._cut_regions: list[tuple[float, float]] = []
        self.signals = get_signals()
        self.video_duration_s = 100.0
        self.mpv_player = None
        self._renders = 0

    def _render_preview(self) -> None:
        self._renders += 1


@pytest.fixture
def ctrl():
    return MockController()


@pytest.fixture
def shared_setup(qapp, ctrl):
    """Symuluje MainWindow: wspólny VideoPreview + podłączone sygnały + RenderTab."""
    preview = VideoPreview()
    preview.set_controller(ctrl)
    s = get_signals()
    s.sig_preview_frame_ready.connect(preview.on_frame_ready)
    s.sig_bboxes_ready.connect(preview.set_bboxes)
    s.sig_video_duration_ready.connect(preview.on_duration_ready)
    s.sig_seek_position.connect(preview._on_seek_position)
    s.sig_cut_region_added.connect(preview._on_cut_region_changed)
    s.sig_cut_region_removed.connect(preview._on_cut_region_changed)
    s.sig_cut_regions_cleared.connect(preview._on_cut_region_changed)
    from src.gui.qt.tabs.render_tab import RenderTab
    rt = RenderTab(preview=preview)
    rt.set_controller(ctrl)
    return preview, rt, ctrl


# ---------------------------------------------------------------------------
# CutMixin.remove_cut_region
# ---------------------------------------------------------------------------

class TestRemoveCutRegion:
    def test_remove_existing(self, ctrl):
        ctrl.add_cut_region(0.0, 10.0)
        ctrl.add_cut_region(90.0, 100.0)
        assert (0.0, 10.0) in ctrl._cut_regions
        ctrl.remove_cut_region(0.0, 10.0)
        assert (0.0, 10.0) not in ctrl._cut_regions
        assert (90.0, 100.0) in ctrl._cut_regions

    def test_remove_missing_is_noop(self, ctrl):
        ctrl.add_cut_region(5.0, 20.0)
        ctrl.remove_cut_region(0.0, 10.0)
        assert ctrl._cut_regions == [(5.0, 20.0)]


# ---------------------------------------------------------------------------
# Współdzielony podgląd
# ---------------------------------------------------------------------------

class TestSharedPreview:
    def test_same_instance_in_both_tabs(self, shared_setup):
        preview, rt, _ = shared_setup
        assert rt.video_preview is preview

    def test_owns_preview_when_standalone(self, qapp):
        from src.gui.qt.tabs.render_tab import RenderTab
        from src.gui.qt.tabs.project_tab import ProjectTab
        rt = RenderTab()
        pt = ProjectTab()
        assert rt._owns_preview
        assert pt._owns_preview
        assert rt.video_preview is not None
        assert pt.video_preview is not None


class TestMainWindowSharing:
    def test_preview_moves_between_tabs(self, qapp):
        from src.gui.qt.main_window import MainWindow
        win = MainWindow()
        qapp.processEvents()

        # Startowo podgląd jest w zakładce Projekt
        assert win.preview.parentWidget() is win._project_tab.preview_slot

        # Przełączenie na Rendering → podgląd przeniesiony
        win.tabs.setCurrentWidget(win._render_tab)
        qapp.processEvents()
        assert win.preview.parentWidget() is win._render_tab.preview_slot

        # Powrót do Projekt → podgląd wraca
        win.tabs.setCurrentWidget(win._project_tab)
        qapp.processEvents()
        assert win.preview.parentWidget() is win._project_tab.preview_slot

        # To ta sama instancja w obu zakładkach (brak duplikacji backendu)
        assert win._project_tab.video_preview is win.preview
        assert win._render_tab.video_preview is win.preview

    def test_set_controller_binds_once(self, qapp):
        from src.gui.qt.main_window import MainWindow
        win = MainWindow()
        calls = []

        class Ctrl:
            def set_video_widget(self, *a):
                calls.append("bind")

        win.set_controller(Ctrl())
        # set_controller wiąże współdzielony podgląd dokładnie raz
        assert len(calls) == 1

    def test_cut_tools_only_in_rendering(self, qapp):
        """Narzędzia wycinania (✂/↩/↩) ukryte w Projekcie, widoczne w Rendering."""
        from src.gui.qt.main_window import MainWindow
        win = MainWindow()
        win.show()
        qapp.processEvents()

        # startowo podgląd w Projekcie → narzędzia ukryte
        assert win.preview.parentWidget() is win._project_tab.preview_slot
        assert not win.preview.cut_btn.isVisible()
        assert not win.preview.undo_cut_btn.isVisible()
        assert not win.preview.restore_cut_btn.isVisible()

        # Rendering → narzędzia widoczne
        win.tabs.setCurrentWidget(win._render_tab)
        qapp.processEvents()
        assert win.preview.parentWidget() is win._render_tab.preview_slot
        assert win.preview.cut_btn.isVisible()
        assert win.preview.undo_cut_btn.isVisible()
        assert win.preview.restore_cut_btn.isVisible()

        # powrót do Projekt → znów ukryte
        win.tabs.setCurrentWidget(win._project_tab)
        qapp.processEvents()
        assert win.preview.parentWidget() is win._project_tab.preview_slot
        assert not win.preview.cut_btn.isVisible()


class TestMpvAvailability:
    """check_mpv_availability — zgłaszanie błędu przy braku libmpv."""

    def test_reports_error_when_missing(self, qapp, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        from src.gui.qt.main_window import MainWindow
        from src.gui.qt import _mixins

        # uniknij modalnego okna w teście
        monkeypatch.setattr(
            QMessageBox, "critical",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
        )
        win = MainWindow()
        errors: list[str] = []
        win.signals.sig_error.connect(errors.append)

        monkeypatch.setattr(_mixins.playback_mixin, "_MPV_AVAILABLE", False)
        win.check_mpv_availability()

        assert len(errors) == 1
        assert "libmpv" in errors[0]

    def test_silent_when_available(self, qapp, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        from src.gui.qt.main_window import MainWindow
        from src.gui.qt import _mixins

        monkeypatch.setattr(
            QMessageBox, "critical",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
        )
        win = MainWindow()
        errors: list[str] = []
        win.signals.sig_error.connect(errors.append)

        monkeypatch.setattr(_mixins.playback_mixin, "_MPV_AVAILABLE", True)
        win.check_mpv_availability()

        assert errors == []


# ---------------------------------------------------------------------------
# Zakres eksportu IN/OUT
# ---------------------------------------------------------------------------

class TestInOutRange:
    def test_set_in_creates_boundary_cut(self, shared_setup):
        _, rt, ctrl = shared_setup
        rt.video_preview.on_duration_ready(100.0)
        rt.video_preview.seek_bar.set_position(10.0)
        rt._on_set_in()
        assert rt._in_orig == 10.0
        assert (0.0, 10.0) in ctrl._cut_regions
        assert rt.lbl_in.text() == "IN: 00:10"

    def test_set_out_creates_boundary_cut(self, shared_setup):
        _, rt, ctrl = shared_setup
        rt.video_preview.on_duration_ready(100.0)
        rt.video_preview.seek_bar.set_position(80.0)
        rt._on_set_out()
        assert rt._out_orig == 80.0
        assert (80.0, 100.0) in ctrl._cut_regions
        assert rt.lbl_out.text() == "OUT: 01:20"

    def test_in_then_out_maps_through_cuts(self, shared_setup):
        """Po ustawieniu IN pozycja OUT liczona jest w czasie oryginalnym."""
        _, rt, ctrl = shared_setup
        rt.video_preview.on_duration_ready(100.0)
        rt.video_preview.seek_bar.set_position(10.0)
        rt._on_set_in()
        # po cięciu [0,10] efektywny suwak ma 90s; pozycja 40 (efektywna) → oryg. 50
        rt.video_preview.seek_bar.set_position(40.0)
        rt._on_set_out()
        assert rt._in_orig == 10.0
        assert rt._out_orig == 50.0
        assert (0.0, 10.0) in ctrl._cut_regions
        assert (50.0, 100.0) in ctrl._cut_regions

    def test_reposition_in_replaces_old_boundary(self, shared_setup):
        _, rt, ctrl = shared_setup
        rt.video_preview.on_duration_ready(100.0)
        rt.video_preview.seek_bar.set_position(10.0)
        rt._on_set_in()
        assert (0.0, 10.0) in ctrl._cut_regions
        # Po cięciu [0,10] suwak jest w czasie efektywnym: pozycja 25 (efektywna)
        # = oryginalne 35. Ponowne ustawienie IN na bieżącej klatce → IN = 35.
        rt.video_preview.seek_bar.set_position(25.0)
        rt._on_set_in()
        assert rt._in_orig == 35.0
        assert (0.0, 10.0) not in ctrl._cut_regions
        assert (0.0, 35.0) in ctrl._cut_regions

    def test_clear_removes_boundary_cuts(self, shared_setup):
        _, rt, ctrl = shared_setup
        rt.video_preview.on_duration_ready(100.0)
        rt.video_preview.seek_bar.set_position(10.0)
        rt._on_set_in()
        rt.video_preview.seek_bar.set_position(80.0)
        rt._on_set_out()
        # 80 (efektywne) po cięciu [0,10] → oryg. 90
        assert (0.0, 10.0) in ctrl._cut_regions
        assert (90.0, 100.0) in ctrl._cut_regions
        rt._on_clear_range()
        assert rt._in_orig is None
        assert rt._out_orig is None
        assert (0.0, 10.0) not in ctrl._cut_regions
        assert (90.0, 100.0) not in ctrl._cut_regions
        assert rt.lbl_in.text() == "IN: --:--"

    def test_invalid_range_auto_clears(self, shared_setup):
        """Defensywnie: gdy nowy punkt IN wypada poza OUT, zakres jest czyszczony."""
        _, rt, _ = shared_setup
        rt.video_preview.on_duration_ready(100.0)
        rt._out_orig = 15.0
        rt.video_preview.seek_bar.set_position(20.0)
        rt._on_set_in()  # IN = 20 > OUT(15) → czyszczenie zakresu
        assert rt._in_orig is None
        assert rt._out_orig is None

    def test_ensure_range_applied_at_render(self, shared_setup):
        """Eksport stosuje zakres IN/OUT jako cięcia graniczne."""
        _, rt, ctrl = shared_setup
        rt.video_preview.on_duration_ready(100.0)
        rt.video_preview.seek_bar.set_position(10.0)
        rt._on_set_in()
        rt.video_preview.seek_bar.set_position(80.0)
        rt._on_set_out()  # OUT = 90 (oryg.)
        rt._ensure_range_applied()
        assert (0.0, 10.0) in ctrl._cut_regions
        assert (90.0, 100.0) in ctrl._cut_regions

    def test_new_video_resets_range(self, shared_setup):
        _, rt, ctrl = shared_setup
        rt.video_preview.on_duration_ready(100.0)
        rt.video_preview.seek_bar.set_position(10.0)
        rt._on_set_in()
        assert rt._in_orig == 10.0
        # nowy film → reset
        rt._on_video_duration_ready(200.0)
        assert rt._in_orig is None
        assert rt._out_orig is None


# ---------------------------------------------------------------------------
# Opcje eksportu — zachowanie istniejących atrybutów
# ---------------------------------------------------------------------------

class TestExportOptions:
    def test_attributes_preserved(self, shared_setup):
        _, rt, _ = shared_setup
        assert hasattr(rt, "cmb_encoder")
        assert hasattr(rt, "cmb_resolution")
        assert hasattr(rt, "cmb_rotation")
        assert hasattr(rt, "cmb_update_rate")
        assert hasattr(rt, "edit_bitrate")
        assert hasattr(rt, "edit_output")
        assert hasattr(rt, "btn_render")
        assert hasattr(rt, "btn_cancel")
        assert hasattr(rt, "progress")
        assert hasattr(rt, "lbl_stats")

    def test_encoder_options(self, shared_setup):
        _, rt, _ = shared_setup
        items = [rt.cmb_encoder.itemText(i) for i in range(rt.cmb_encoder.count())]
        assert items == ["amd", "nv", "intel", "cpu"]

    def test_render_options_dict(self, shared_setup):
        _, rt, _ = shared_setup
        rt.edit_output.setText("out.mp4")
        options = {
            "encoder": rt.cmb_encoder.currentText(),
            "resolution": rt.cmb_resolution.currentText(),
            "rotation": rt.cmb_rotation.currentText(),
            "update_rate": rt.cmb_update_rate.currentText(),
            "bitrate": rt.edit_bitrate.text().strip(),
            "output": rt.edit_output.text().strip(),
        }
        assert options["output"] == "out.mp4"
        assert options["encoder"] in ("nv", "amd", "intel", "cpu")
