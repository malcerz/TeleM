"""Zakładka Rendering — opcje eksportu i przycisk Renderuj."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QComboBox,
    QLineEdit, QPushButton, QHBoxLayout, QProgressBar, QLabel,
    QFileDialog, QMessageBox,
)

from src.gui.qt.signals import get_signals


class RenderTab(QWidget):
    """Zakładka opcji renderowania."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setAlignment(Qt.AlignTop)
        vbox.setContentsMargins(24, 24, 24, 24)

        group = QGroupBox("Opcje eksportu")
        group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        form = QFormLayout(group)
        form.setSpacing(10)

        self.cmb_encoder = QComboBox()
        self.cmb_encoder.addItems(["nv", "intel", "cpu"])
        self.cmb_encoder.setToolTip("nv = NVIDIA NVENC, intel = Intel QuickSync, cpu = software")
        form.addRow("Encoder:", self.cmb_encoder)

        self.cmb_resolution = QComboBox()
        self.cmb_resolution.addItems(
            ["source", "8k", "5.3k", "4k", "1080p", "720p", "480p"]
        )
        form.addRow("Rozdzielczość:", self.cmb_resolution)

        self.cmb_rotation = QComboBox()
        self.cmb_rotation.addItems(["auto", "0", "90", "180", "270"])
        form.addRow("Rotacja:", self.cmb_rotation)

        self.cmb_update_rate = QComboBox()
        self.cmb_update_rate.addItems(["Full", "Half", "Quarter"])
        form.addRow("Częstotliwość HUD:", self.cmb_update_rate)

        self.edit_bitrate = QLineEdit("40M")
        form.addRow("Bitrate:", self.edit_bitrate)

        row_out = QHBoxLayout()
        self.edit_output = QLineEdit("output_h265.mp4")
        self.edit_output.setMinimumHeight(28)
        row_out.addWidget(self.edit_output)
        btn_out = QPushButton("Wybierz")
        btn_out.setMinimumHeight(28)
        btn_out.clicked.connect(self._select_output)
        row_out.addWidget(btn_out)
        form.addRow("Plik wyjściowy:", row_out)

        vbox.addWidget(group)

        # Przyciski
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_render = QPushButton("Renderuj")
        self.btn_render.setMinimumHeight(48)
        self.btn_render.setMinimumWidth(160)
        self.btn_render.setStyleSheet(
            "QPushButton { background-color: #d44000; color: white; "
            "font-size: 14px; font-weight: bold; border: none; "
            "border-radius: 4px; padding: 8px 24px; }"
            "QPushButton:hover { background-color: #e45010; }"
            "QPushButton:disabled { background-color: #555; }"
        )
        self.btn_render.clicked.connect(self._on_render)
        btn_row.addWidget(self.btn_render)

        self.btn_cancel = QPushButton("Anuluj")
        self.btn_cancel.setMinimumHeight(48)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)

        vbox.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        vbox.addWidget(self.progress)

        self.lbl_stats = QLabel("Gotowy")
        self.lbl_stats.setStyleSheet("color: #888;")
        vbox.addWidget(self.lbl_stats)

        vbox.addStretch()

    def _connect_signals(self) -> None:
        s = self.signals
        s.sig_progress.connect(self._on_progress)
        s.sig_render_finished.connect(self._on_finished)
        s.sig_error.connect(self._on_error)

    def _select_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Plik wyjściowy", "", "MP4 (*.mp4)",
        )
        if path:
            self.edit_output.setText(path)

    def _on_render(self) -> None:
        options = {
            "encoder": self.cmb_encoder.currentText(),
            "resolution": self.cmb_resolution.currentText(),
            "rotation": self.cmb_rotation.currentText(),
            "update_rate": self.cmb_update_rate.currentText(),
            "bitrate": self.edit_bitrate.text().strip(),
            "output": self.edit_output.text().strip(),
        }
        self.btn_render.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.lbl_stats.setText("Renderowanie...")
        self.signals.sig_render_requested.emit(options)

    def _on_cancel(self) -> None:
        self.signals.sig_render_cancelled.emit()
        self._reset_ui()

    def _on_progress(self, percent: int, text: str) -> None:
        self.progress.setValue(percent)
        self.lbl_stats.setText(text)

    def _on_finished(self, _stats: dict, output: str) -> None:
        self._reset_ui()
        QMessageBox.information(
            self, "Eksport zakończony",
            f"Plik zapisany:\n{output}",
        )

    def _on_error(self, msg: str) -> None:
        if self.btn_render:
            self._reset_ui()
            self.lbl_stats.setText(f"Błąd: {msg}")

    def _reset_ui(self) -> None:
        self.btn_render.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
