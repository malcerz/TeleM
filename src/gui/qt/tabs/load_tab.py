"""Zakładka Wczytywanie — wybór plików MP4, GPX, FIT."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QPushButton,
    QLabel, QLineEdit, QHBoxLayout, QFileDialog, QMessageBox,
)

from src.gui.qt.signals import get_signals


class LoadTab(QWidget):
    """Zakładka wyboru plików źródłowych."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._video_paths: list[str] = []
        self._gpx_path: str = ""
        self._fit_path: str = ""
        self._build_ui()

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setAlignment(Qt.AlignTop)
        vbox.setContentsMargins(24, 24, 24, 24)

        # ── Sekcja MP4 (wymagane) ──────────────────────────────────────
        group = QGroupBox("Pliki źródłowe")
        group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        form = QFormLayout(group)
        form.setSpacing(12)

        # MP4
        row_mp4 = QHBoxLayout()
        self.edit_mp4 = QLineEdit()
        self.edit_mp4.setReadOnly(True)
        self.edit_mp4.setPlaceholderText("Wybierz plik(i) MP4...")
        self.edit_mp4.setMinimumHeight(28)
        row_mp4.addWidget(self.edit_mp4)
        btn_mp4 = QPushButton("Wybierz")
        btn_mp4.setMinimumHeight(28)
        btn_mp4.clicked.connect(self._select_mp4)
        row_mp4.addWidget(btn_mp4)
        form.addRow("MP4 (wymagane):", row_mp4)

        # GPX
        row_gpx = QHBoxLayout()
        self.edit_gpx = QLineEdit()
        self.edit_gpx.setReadOnly(True)
        self.edit_gpx.setPlaceholderText("(opcjonalnie)")
        self.edit_gpx.setMinimumHeight(28)
        row_gpx.addWidget(self.edit_gpx)
        btn_gpx = QPushButton("Wybierz")
        btn_gpx.setMinimumHeight(28)
        btn_gpx.clicked.connect(self._select_gpx)
        row_gpx.addWidget(btn_gpx)
        form.addRow("GPX:", row_gpx)

        # FIT
        row_fit = QHBoxLayout()
        self.edit_fit = QLineEdit()
        self.edit_fit.setReadOnly(True)
        self.edit_fit.setPlaceholderText("(opcjonalnie)")
        self.edit_fit.setMinimumHeight(28)
        row_fit.addWidget(self.edit_fit)
        btn_fit = QPushButton("Wybierz")
        btn_fit.setMinimumHeight(28)
        btn_fit.clicked.connect(self._select_fit)
        row_fit.addWidget(btn_fit)
        form.addRow("FIT:", row_fit)

        vbox.addWidget(group)

        # ── Przyciski akcji ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_load = QPushButton("Wczytaj")
        self.btn_load.setMinimumHeight(48)
        self.btn_load.setMinimumWidth(160)
        self.btn_load.setStyleSheet(
            "QPushButton { background-color: #0078d4; color: white; "
            "font-size: 14px; font-weight: bold; border: none; "
            "border-radius: 4px; padding: 8px 24px; }"
            "QPushButton:hover { background-color: #1084d4; }"
            "QPushButton:disabled { background-color: #555; }"
        )
        self.btn_load.clicked.connect(self._on_load)
        btn_row.addWidget(self.btn_load)

        self.btn_clear = QPushButton("Wyczyść")
        self.btn_clear.setMinimumHeight(48)
        self.btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(self.btn_clear)

        vbox.addLayout(btn_row)

        # Informacja
        self.lbl_info = QLabel("Nie wczytano plików.")
        self.lbl_info.setStyleSheet("color: #888; font-size: 12px;")
        vbox.addWidget(self.lbl_info)

        vbox.addStretch()

    def _select_mp4(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Wybierz plik(i) MP4", "",
            "Wideo (*.mp4 *.MP4 *.mov *.MOV)",
        )
        if paths:
            self.edit_mp4.setText("; ".join(paths))
            self._video_paths = paths

    def _select_gpx(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik GPX", "",
            "GPX (*.gpx *.GPX)",
        )
        if path:
            self.edit_gpx.setText(path)
            self._gpx_path = path

    def _select_fit(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik FIT", "",
            "FIT (*.fit *.FIT)",
        )
        if path:
            self.edit_fit.setText(path)
            self._fit_path = path

    def _on_load(self) -> None:
        if not self._video_paths:
            QMessageBox.warning(self, "Brak pliku", "Wybierz plik MP4.")
            return

        self.btn_load.setEnabled(False)
        self.lbl_info.setText("Wczytywanie...")
        self.signals.sig_files_selected.emit(
            self._video_paths, self._gpx_path, self._fit_path,
        )

        # Przywróć przycisk po zakończeniu
        self.signals.sig_progress.connect(self._on_loading_done)

    def _on_loading_done(self, percent: int, _text: str) -> None:
        if percent >= 100:
            self.btn_load.setEnabled(True)
            self.lbl_info.setText("Wczytano pomyślnie.")
            try:
                self.signals.sig_progress.disconnect(self._on_loading_done)
            except Exception:
                pass

    def _on_clear(self) -> None:
        self.edit_mp4.clear()
        self.edit_gpx.clear()
        self.edit_fit.clear()
        self._video_paths = []
        self._gpx_path = ""
        self._fit_path = ""
        self.lbl_info.setText("Nie wczytano plików.")
