"""Zakładka Wczytywanie — wybór plików MP4, GPX, FIT."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QPushButton,
    QLabel, QHBoxLayout, QFileDialog, QMessageBox, QComboBox,
)

from src.gui.qt.signals import get_signals
from src.gui.qt.mpv_hwdec import detect_preview_vendor, get_available_vendors, vendor_label


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

        # ── Sekcja Pliki źródłowe ──────────────────────────────────────
        group = QGroupBox("Pliki źródłowe")
        group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        form = QFormLayout(group)
        form.setSpacing(14)

        # Szerokie paski stylizowane na pola wejściowe z obsługą kliknięcia
        self._placeholder_style = (
            "QPushButton { text-align: left; padding: 4px 12px; background-color: #ffffff; "
            "color: #666666; border: 1px solid #cccccc; border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background-color: #f5f5f5; border-color: #999999; color: #333333; }"
        )
        self._selected_style = (
            "QPushButton { text-align: left; padding: 4px 12px; background-color: #ffffff; "
            "color: #111111; border: 1.5px solid #0078d4; border-radius: 4px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #f0f7ff; border-color: #1084d4; }"
        )

        # MP4 bar
        self.btn_mp4 = QPushButton("Wybierz plik(i) MP4...")
        self.btn_mp4.setMinimumHeight(34)
        self.btn_mp4.setCursor(Qt.PointingHandCursor)
        self.btn_mp4.setStyleSheet(self._placeholder_style)
        self.btn_mp4.clicked.connect(self._select_mp4)
        form.addRow("MP4 (wymagane):", self.btn_mp4)

        # Telemetry bar (FIT / GPX)
        self.btn_telemetry = QPushButton("Wybierz FIT/GPX (opcjonalnie)...")
        self.btn_telemetry.setMinimumHeight(34)
        self.btn_telemetry.setCursor(Qt.PointingHandCursor)
        self.btn_telemetry.setStyleSheet(self._placeholder_style)
        self.btn_telemetry.clicked.connect(self._select_telemetry)
        form.addRow("FIT / GPX:", self.btn_telemetry)

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

        # ── Akcelerator podglądu (nowy) ───────────────────────────────────
        accel_row = QHBoxLayout()
        accel_row.setContentsMargins(0, 2, 0, 2)
        accel_row.setSpacing(6)
        lbl_gpu = QLabel("Podgląd GPU:")
        lbl_gpu.setStyleSheet("color: #aaa; font-size: 12px;")
        lbl_gpu.setFixedWidth(80)
        accel_row.addWidget(lbl_gpu)

        self.cmb_preview_accel = QComboBox()
        self.cmb_preview_accel.setMinimumWidth(140)
        self.cmb_preview_accel.setStyleSheet(
            "QComboBox { background-color: #2a2a2a; color: #ddd; "
            "border: 1px solid #555; border-radius: 3px; padding: 2px 8px; font-size: 12px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background-color: #2a2a2a; color: #ddd; selection-background-color: #0078d4; }"
        )

        # Populate with "Auto" + detected vendors
        self.cmb_preview_accel.addItem("Auto", "auto")
        best = detect_preview_vendor()
        for code in get_available_vendors():
            self.cmb_preview_accel.addItem(vendor_label(code), code)

        # Pre-select "Auto"
        self.cmb_preview_accel.setCurrentIndex(0)
        self.cmb_preview_accel.currentIndexChanged.connect(self._on_accel_changed)
        accel_row.addWidget(self.cmb_preview_accel)
        accel_row.addStretch()
        vbox.addLayout(accel_row)

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
            self._video_paths = paths
            self.btn_mp4.setText("; ".join(paths))
            self.btn_mp4.setStyleSheet(self._selected_style)

    def _select_telemetry(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik FIT lub GPX", "",
            "Pliki telemetryczne (*.fit *.FIT *.gpx *.GPX);;FIT (*.fit *.FIT);;GPX (*.gpx *.GPX)",
        )
        if path:
            ext = path.lower()
            if ext.endswith(".fit"):
                self._fit_path = path
                self._gpx_path = ""
            elif ext.endswith(".gpx"):
                self._gpx_path = path
                self._fit_path = ""
            self.btn_telemetry.setText(path)
            self.btn_telemetry.setStyleSheet(self._selected_style)

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

    def _on_accel_changed(self, _index: int) -> None:
        """Emit preview accelerator changed when the user picks a new GPU."""
        vendor = self.cmb_preview_accel.currentData()
        self.signals.sig_preview_accel_changed.emit(vendor or "auto")

    def _on_clear(self) -> None:
        self.btn_mp4.setText("Wybierz plik(i) MP4...")
        self.btn_mp4.setStyleSheet(self._placeholder_style)
        self.btn_telemetry.setText("Wybierz FIT/GPX (opcjonalnie)...")
        self.btn_telemetry.setStyleSheet(self._placeholder_style)
        self._video_paths = []
        self._gpx_path = ""
        self._fit_path = ""
        self.lbl_info.setText("Nie wczytano plików.")
