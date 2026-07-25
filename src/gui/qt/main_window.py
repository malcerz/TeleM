"""Główne okno aplikacji — QMainWindow z czterema zakładkami."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QProgressBar, QLabel, QMessageBox,
)

from src.gui.qt.signals import get_signals
from src.gui.qt.tabs.load_tab import LoadTab
from src.gui.qt.tabs.project_tab import ProjectTab
from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.tabs.settings_tab import SettingsTab


APP_TITLE = "TeleMGP HUD Tuner"
APP_VERSION = "0.7.9"


class MainWindow(QMainWindow):
    """Główne okno aplikacji z QTabWidget."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 1000)

        self.signals = get_signals()

        # ── Centralny widget: QTabWidget ────────────────────────────────
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # ── Zakładki ────────────────────────────────────────────────────
        self._load_tab = LoadTab()
        self._project_tab = ProjectTab()
        self._render_tab = RenderTab()
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

        # Po załadowaniu danych przełącz na zakładkę Projekt
        self.signals.sig_data_streams_ready.connect(
            lambda _: self.tabs.setCurrentWidget(self._project_tab)
        )

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
