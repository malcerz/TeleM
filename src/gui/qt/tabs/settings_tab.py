"""Zakładka Ustawienia — konfiguracja programu."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QComboBox,
    QSpinBox, QPushButton, QLineEdit, QHBoxLayout, QFileDialog,
    QStyleFactory,
)
from PySide6.QtGui import QFontDatabase

from src.gui.qt.signals import get_signals


class SettingsTab(QWidget):
    """Zakładka ustawień aplikacji."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._build_ui()

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setAlignment(Qt.AlignTop)
        vbox.setContentsMargins(24, 24, 24, 24)

        # ── Ogólne ────────────────────────────────────────────────────
        general = QGroupBox("Ogólne")
        general.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        form = QFormLayout(general)
        form.setSpacing(10)

        self.cmb_lang = QComboBox()
        self.cmb_lang.addItems(["Polski", "English"])
        form.addRow("Język:", self.cmb_lang)

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(QStyleFactory.keys())
        current = QStyleFactory.keys()
        if "Fusion" in current:
            self.cmb_theme.setCurrentText("Fusion")
        form.addRow("Motyw:", self.cmb_theme)

        # Startowy preset
        row_preset = QHBoxLayout()
        self.edit_startup_preset = QLineEdit("")
        self.edit_startup_preset.setMinimumHeight(28)
        self.edit_startup_preset.setPlaceholderText("(domyślny def_layout.json)")
        self.edit_startup_preset.textChanged.connect(
            lambda txt: self.signals.sig_settings_changed.emit("startup_preset", txt)
        )
        row_preset.addWidget(self.edit_startup_preset)
        btn_preset = QPushButton("Wybierz")
        btn_preset.setMinimumHeight(28)
        btn_preset.clicked.connect(
            lambda: self._browse_file(self.edit_startup_preset, "preset")
        )
        row_preset.addWidget(btn_preset)
        btn_clear = QPushButton("Wyczyść")
        btn_clear.setMinimumHeight(28)
        btn_clear.clicked.connect(lambda: self.edit_startup_preset.setText(""))
        row_preset.addWidget(btn_clear)
        form.addRow("Startowy preset:", row_preset)

        vbox.addWidget(general)

        # ── Czcionka HUD ──────────────────────────────────────────────
        font_group = QGroupBox("Czcionka HUD")
        font_group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        font_form = QFormLayout(font_group)
        font_form.setSpacing(10)

        self.cmb_font = QComboBox()
        families = QFontDatabase().families()
        self.cmb_font.addItems(families)
        if "Arial" in families:
            self.cmb_font.setCurrentText("Arial")
        self.cmb_font.currentTextChanged.connect(
            lambda f: self.signals.sig_settings_changed.emit("font", f)
        )
        font_form.addRow("Czcionka:", self.cmb_font)

        self.spin_outline = QSpinBox()
        self.spin_outline.setRange(0, 10)
        self.spin_outline.setValue(3)
        self.spin_outline.valueChanged.connect(
            lambda v: self.signals.sig_settings_changed.emit("outline", v)
        )
        font_form.addRow("Obramowanie:", self.spin_outline)

        vbox.addWidget(font_group)

        # ── Wydajność ─────────────────────────────────────────────────
        perf_group = QGroupBox("Wydajność")
        perf_group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        perf_form = QFormLayout(perf_group)
        perf_form.setSpacing(10)

        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 32)
        self.spin_threads.setValue(8)
        perf_form.addRow("Liczba wątków:", self.spin_threads)

        row_cache = QHBoxLayout()
        self.edit_cache = QLineEdit("cache/")
        self.edit_cache.setMinimumHeight(28)
        row_cache.addWidget(self.edit_cache)
        btn_cache = QPushButton("Wybierz")
        btn_cache.setMinimumHeight(28)
        btn_cache.clicked.connect(lambda: self._browse_dir(self.edit_cache))
        row_cache.addWidget(btn_cache)
        perf_form.addRow("Katalog cache:", row_cache)

        # Ścieżka ffmpeg
        row_ffmpeg = QHBoxLayout()
        self.edit_ffmpeg = QLineEdit("")
        self.edit_ffmpeg.setMinimumHeight(28)
        self.edit_ffmpeg.setPlaceholderText("(auto-wykrywanie)")
        row_ffmpeg.addWidget(self.edit_ffmpeg)
        btn_ffmpeg = QPushButton("Wybierz")
        btn_ffmpeg.setMinimumHeight(28)
        btn_ffmpeg.clicked.connect(lambda: self._browse_file(self.edit_ffmpeg, "ffmpeg"))
        row_ffmpeg.addWidget(btn_ffmpeg)
        perf_form.addRow("Ścieżka ffmpeg:", row_ffmpeg)

        vbox.addWidget(perf_group)

        vbox.addStretch()

    def _browse_dir(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Wybierz katalog")
        if path:
            target.setText(path)

    def _browse_file(self, target: QLineEdit, _name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik", "", "Wszystkie (*)",
        )
        if path:
            target.setText(path)
