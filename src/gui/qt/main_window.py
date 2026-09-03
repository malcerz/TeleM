"""Główne okno aplikacji — QMainWindow z czterema zakładkami."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QProgressBar, QLabel, QMessageBox,
    QWidget,
)

from src.gui.qt.signals import get_signals
from src.gui.qt.tabs.load_tab import LoadTab
from src.gui.qt.tabs.project_tab import ProjectTab
from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.tabs.settings_tab import SettingsTab
from src.gui.qt.widgets.video_preview import VideoPreview


APP_TITLE = "TeleMGP HUD Tuner"
APP_VERSION = "0.7.9"


class MainWindow(QMainWindow):
    """Główne okno aplikacji z QTabWidget.

    Zakładki Projekt i Rendering WSPÓŁDZIELĄ jedną instancję VideoPreview
    (``self.preview``). Podgląd jest przenoszony (reparentowany) do aktywnej
    zakładki — backend wideo wiąże się z podglądem tylko raz, więc nie powstają
    konfliktujące instancje podczas przełączania zakładek.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 1000)

        self.signals = get_signals()

        # ── Współdzielony podgląd wideo (Projekt ↔ Rendering) ───────────
        self.preview = VideoPreview()

        # ── Centralny widget: QTabWidget ────────────────────────────────
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._preview_fullscreen: bool = False
        self._fullscreen_saved_central = None

        # ── Zakładki ────────────────────────────────────────────────────
        self._load_tab = LoadTab()
        self._project_tab = ProjectTab(preview=self.preview)
        self._render_tab = RenderTab(preview=self.preview)
        self._settings_tab = SettingsTab()

        self.tabs.addTab(self._load_tab, "Wczytywanie")
        self.tabs.addTab(self._project_tab, "Projekt")
        self.tabs.addTab(self._render_tab, "Rendering")
        self.tabs.addTab(self._settings_tab, "Ustawienia")

        # ── Status bar ──────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_label = QLabel("Gotowy")
        self.status_bar.addWidget(self.status_label, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(300)
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.status_bar.addPermanentWidget(self.progress_bar)

        # ── Podłącz sygnały kontrolera do UI ────────────────────────────
        self._connect_controller_signals()
        self._connect_preview_signals()

        # Umieść współdzielony podgląd w zakładce Projekt (startowa)
        self._move_preview_to(self._project_tab.preview_slot)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Po załadowaniu danych przełącz na zakładkę Projekt
        self.signals.sig_data_streams_ready.connect(self._on_data_streams_ready)

    def _on_data_streams_ready(self, _streams) -> None:
        self.tabs.setCurrentWidget(self._project_tab)
        self.preview._notify_controller_preview_size()
        if hasattr(self, "_controller") and self._controller:
            if hasattr(self._controller, "refresh_preview_geometry_and_hud"):
                self._controller.refresh_preview_geometry_and_hud()

    def set_controller(self, controller: object) -> None:
        """Bind kontroler do współdzielonego podglądu (jeden raz).

        Wywoływane z application.py po utworzeniu MainWindow.
        """
        self._controller = controller
        self.preview.set_controller(controller)
        self._project_tab.set_controller(controller)
        self._render_tab.set_controller(controller)


    def check_mpv_availability(self) -> None:
        """Zgłoś błąd, gdy program nie wykryje bibliotek libmpv.

        Odczytuje wynik detekcji z backendu (playback_mixin._MPV_AVAILABLE) —
        nie modyfikuje backendu. Wywoływane z application.py po pokazaniu okna.
        """
        try:
            from src.gui.qt._mixins.playback_mixin import _MPV_AVAILABLE
        except Exception:
            _MPV_AVAILABLE = False
        if _MPV_AVAILABLE:
            return
        self.signals.sig_error.emit(
            "Nie wykryto bibliotek libmpv (mpv-2.dll / libmpv-2.dll).\n\n"
            "Sprzętowy podgląd GPU (MPV) będzie niedostępny — aplikacja "
            "użyje fallbacku QMediaPlayer.\n\n"
            "Rozwiązanie: pobierz mpv (np. pakiet mpv-dev) i umieść plik DLL "
            "libmpv w katalogu programu lub w PATH systemowym."
        )

    def _connect_preview_signals(self) -> None:
        """Podłącz sygnały podglądu — dokładnie raz (współdzielona instancja)."""
        s = self.signals
        s.sig_preview_frame_ready.connect(self.preview.on_frame_ready)
        s.sig_bboxes_ready.connect(self.preview.set_bboxes)
        s.sig_video_duration_ready.connect(self.preview.on_duration_ready)
        s.sig_seek_position.connect(self.preview._on_seek_position)
        s.sig_toggle_fullscreen.connect(self.toggle_fullscreen_preview)

    def _move_preview_to(self, slot: QWidget) -> None:
        """Przenieś współdzielony podgląd do kontenera aktywnej zakładki."""
        if self.preview.parentWidget() is slot:
            return
        old = self.preview.parentWidget()
        if old is not None and old.layout() is not None:
            old.layout().removeWidget(self.preview)
        self.preview.setParent(slot)
        slot.layout().addWidget(self.preview)
        self.preview.show()

    def _on_tab_changed(self, index: int) -> None:
        """Przy zmianie zakładki przenieś podgląd do zakładki z kontenerem."""
        current = self.tabs.widget(index)
        slot = getattr(current, "preview_slot", None)
        if slot is not None:
            self._move_preview_to(slot)
            self.preview._notify_controller_preview_size()
            if hasattr(self, "_controller") and self._controller:
                if hasattr(self._controller, "refresh_preview_geometry_and_hud"):
                    self._controller.refresh_preview_geometry_and_hud()


    def _connect_controller_signals(self) -> None:
        s = self.signals
        s.sig_progress.connect(self._on_progress)
        s.sig_error.connect(self._on_error)
        s.sig_video_info_ready.connect(self._on_video_info)

    def _on_progress(self, percent: int, text: str) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(percent)
        self.status_label.setText(text)
        if percent >= 100:
            self.progress_bar.setVisible(False)

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"Błąd: {msg}")
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Błąd", msg)

    def _on_video_info(self, info: str) -> None:
        self.status_label.setText(f"Wideo: {info}")

    @property
    def _is_fullscreen_preview(self) -> bool:
        return self._preview_fullscreen

    def enter_fullscreen_preview(self) -> None:
        """Wejdź w tryb True Fullscreen — zachowuje tabs bez niszczenia przez Qt."""
        if getattr(self, "_preview_fullscreen", False):
            return

        self._was_maximized = self.isMaximized()
        self._saved_preview_slot = self.preview.parentWidget()

        # Bezpiecznie zdejmij centralny widget (tabs) przejmując ownership w Pythonie
        normal_central = self.takeCentralWidget()
        self._fullscreen_saved_central = normal_central
        if normal_central is not None:
            normal_central.hide()

        # Wyjmij preview ze slotu w zakładce
        if self._saved_preview_slot is not None and self._saved_preview_slot.layout() is not None:
            self._saved_preview_slot.layout().removeWidget(self.preview)

        self.status_bar.hide()
        if self.menuBar() is not None:
            self.menuBar().hide()

        self.setCentralWidget(self.preview)
        self.preview.show()
        self.showFullScreen()
        self._preview_fullscreen = True

        self.preview._notify_controller_preview_size()
        if hasattr(self.preview, "hud_overlay") and self.preview.hud_overlay:
            self.preview.hud_overlay.sync_geometry()
        if self._controller and hasattr(self._controller, "refresh_preview_geometry_and_hud"):
            self._controller.refresh_preview_geometry_and_hud()
        if hasattr(self.preview, "print_preview_raster_diag"):
            self.preview.print_preview_raster_diag()

    def exit_fullscreen_preview(self) -> None:
        """Wyjdź z trybu True Fullscreen — bezpiecznie przywróć tabs i wstaw preview na miejsce."""
        if not getattr(self, "_preview_fullscreen", False):
            return

        # Zdejmij preview z central widgetu, by QMainWindow nie usunął go przy setCentralWidget
        preview = self.takeCentralWidget()

        # Przywróć oryginalny central widget (tabs)
        if getattr(self, "_fullscreen_saved_central", None) is not None:
            self.setCentralWidget(self._fullscreen_saved_central)
            self._fullscreen_saved_central.show()
            self._fullscreen_saved_central = None
        else:
            self.setCentralWidget(self.tabs)
            self.tabs.show()

        target_slot = getattr(self, "_saved_preview_slot", None) or self._project_tab.preview_slot
        self._move_preview_to(target_slot)

        if self.menuBar() is not None:
            self.menuBar().show()
        self.status_bar.show()

        if getattr(self, "_was_maximized", False):
            self.showMaximized()
        else:
            self.showNormal()
        self._preview_fullscreen = False

        self.preview._notify_controller_preview_size()
        if hasattr(self.preview, "hud_overlay") and self.preview.hud_overlay:
            self.preview.hud_overlay.sync_geometry()
        if self._controller and hasattr(self._controller, "refresh_preview_geometry_and_hud"):
            self._controller.refresh_preview_geometry_and_hud()

    def toggle_fullscreen_preview(self) -> None:
        """Przełącz tryb True Fullscreen — cały ekran zajmuje tylko podgląd (wideo + HUD)."""
        if getattr(self, "_preview_fullscreen", False):
            self.exit_fullscreen_preview()
        else:
            self.enter_fullscreen_preview()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            if getattr(self, "_preview_fullscreen", False):
                self.exit_fullscreen_preview()
                event.accept()
                return
        elif key == Qt.Key_Space:
            if hasattr(self, "preview") and hasattr(self.preview, "_toggle_playback"):
                self.preview._toggle_playback()
                event.accept()
                return
        elif key == Qt.Key_Left:
            self.signals.sig_frame_step.emit(-1)
            event.accept()
            return
        elif key == Qt.Key_Right:
            self.signals.sig_frame_step.emit(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        """Zamykanie okna — brak automatycznego zapisu (zapis tylko po jawnym kliknięciu 'Zapisz ustawienia')."""
        super().closeEvent(event)
