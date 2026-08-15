"""Zakładka Rendering — podgląd wideo + opcje eksportu.

Układ poziomy:
- ~75% po lewej: współdzielony podgląd wideo + pasek zakresu eksportu (IN/OUT)
- ~25% po prawej: istniejące Opcje eksportu
- dół (cała szerokość): przycisk Eksportuj + postęp + status

Podgląd jest WSPÓŁDZIELONY z zakładką Projekt (ta sama instancja VideoPreview,
przenoszona przez MainWindow między zakładkami) — zakładka NIE tworzy drugiego,
niezależnego systemu podglądu. Wszystkie istniejące opcje eksportu zostały
zachowane bez zmian funkcjonalnych.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QComboBox,
    QLineEdit, QPushButton, QProgressBar, QLabel, QFileDialog, QMessageBox,
    QScrollArea, QFrame, QSizePolicy,
)

from src.gui.qt.signals import get_signals
from src.gui.qt.widgets.video_preview import VideoPreview, preview_aspect_size


class RenderTab(QWidget):
    """Zakładka opcji renderowania z podglądem i zakresem eksportu IN/OUT."""

    def __init__(self, preview: VideoPreview | None = None) -> None:
        super().__init__()
        self.signals = get_signals()
        self._controller: object = None
        self._owns_preview = preview is None
        self.video_preview = preview if preview is not None else VideoPreview()
        # Zakres eksportu IN/OUT w oryginalnym czasie
        self._in_orig: float | None = None
        self._out_orig: float | None = None
        self._boundary_regions: list[tuple[float, float]] = []
        self._build_ui()
        self._connect_signals()
        if self._owns_preview:
            self._connect_preview_signals()

    # ═════════════════════════════════════════════════════════════════════
    # Budowa UI
    # ═════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # ── Poziom główny: ~75% podgląd / ~25% opcje ────────────────────
        main = QHBoxLayout()
        main.setSpacing(8)

        # LEWY (~75%): podgląd + zakres IN/OUT
        self.left_panel = QWidget()
        self.left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self.preview_slot = QWidget()
        self.preview_slot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_slot_layout = QVBoxLayout(self.preview_slot)
        self.preview_slot_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_slot_layout.setSpacing(0)
        left_layout.addWidget(self.preview_slot, 0, Qt.AlignHCenter)
        if self._owns_preview:
            self.preview_slot_layout.addWidget(self.video_preview)

        left_layout.addLayout(self._build_inout_bar())
        left_layout.addStretch(1)

        main.addWidget(self.left_panel, 3)  # 75%

        # PRAWY (~25%): Opcje eksportu (istniejące ustawienia)
        self.right_panel = QWidget()
        self.right_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.right_panel.setMinimumWidth(280)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Opcje eksportu")
        group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        form = QFormLayout(group)
        form.setSpacing(10)

        self.cmb_encoder = QComboBox()
        self.cmb_encoder.addItems(["nv", "amd", "intel", "cpu"])
        self.cmb_encoder.setToolTip("nv = NVIDIA NVENC, amd = AMD AMF, intel = Intel QuickSync, cpu = software")
        try:
            from src.ffmpeg_pipeline import detect_best_encoder
            best_enc = detect_best_encoder()
            idx = self.cmb_encoder.findText(best_enc)
            if idx >= 0:
                self.cmb_encoder.setCurrentIndex(idx)
        except Exception:
            pass
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

        # Scroll — opcje mieszczą się w 25% nawet przy małym oknie
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(group)
        right_layout.addWidget(scroll, 1)

        main.addWidget(self.right_panel, 1)  # 25%

        vbox.addLayout(main, 1)

        # ── Dolny pasek: Eksportuj + postęp + status ────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        self.btn_render = QPushButton("Eksportuj")
        self.btn_render.setMinimumHeight(48)
        self.btn_render.setMinimumWidth(180)
        self.btn_render.setStyleSheet(
            "QPushButton { background-color: #d44000; color: white; "
            "font-size: 14px; font-weight: bold; border: none; "
            "border-radius: 4px; padding: 8px 24px; }"
            "QPushButton:hover { background-color: #e45010; }"
            "QPushButton:disabled { background-color: #555; }"
        )
        self.btn_render.clicked.connect(self._on_render)
        bottom.addWidget(self.btn_render, 1)

        self.btn_cancel = QPushButton("Anuluj")
        self.btn_cancel.setMinimumHeight(48)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        bottom.addWidget(self.btn_cancel)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMinimumWidth(180)
        bottom.addWidget(self.progress, 1)

        self.lbl_stats = QLabel("Gotowy")
        self.lbl_stats.setStyleSheet("color: #888;")
        bottom.addWidget(self.lbl_stats)

        vbox.addLayout(bottom)

    def _build_inout_bar(self) -> QHBoxLayout:
        """Pasek narzędzi zakresu eksportu: IN / OUT / Wyczyść."""
        row = QHBoxLayout()
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(8)

        self.btn_in = QPushButton("IN")
        self.btn_in.setFixedHeight(26)
        self.btn_in.setToolTip("Ustaw punkt początku eksportu (IN) na aktualnej pozycji")
        self.btn_in.clicked.connect(self._on_set_in)

        self.lbl_in = QLabel("IN: --:--")
        self.lbl_in.setStyleSheet("color: #ffd75e; font-weight: bold;")

        self.btn_out = QPushButton("OUT")
        self.btn_out.setFixedHeight(26)
        self.btn_out.setToolTip("Ustaw punkt końca eksportu (OUT) na aktualnej pozycji")
        self.btn_out.clicked.connect(self._on_set_out)

        self.lbl_out = QLabel("OUT: --:--")
        self.lbl_out.setStyleSheet("color: #ff8a8a; font-weight: bold;")

        self.lbl_range_len = QLabel("Zakres: --:--")
        self.lbl_range_len.setStyleSheet("color: #aaa;")

        self.btn_clear_range = QPushButton("Wyczyść zakres")
        self.btn_clear_range.setFixedHeight(26)
        self.btn_clear_range.setToolTip("Usuń zaznaczony zakres IN/OUT")
        self.btn_clear_range.clicked.connect(self._on_clear_range)

        row.addWidget(self.btn_in)
        row.addWidget(self.lbl_in)
        row.addWidget(self.btn_out)
        row.addWidget(self.lbl_out)
        row.addWidget(self.lbl_range_len)
        row.addStretch()
        row.addWidget(self.btn_clear_range)
        return row

    # ═════════════════════════════════════════════════════════════════════
    # Sygnały
    # ═════════════════════════════════════════════════════════════════════

    def _connect_signals(self) -> None:
        s = self.signals
        s.sig_progress.connect(self._on_progress)
        s.sig_render_finished.connect(self._on_finished)
        s.sig_error.connect(self._on_error)
        s.sig_video_duration_ready.connect(self._on_video_duration_ready)

    def _connect_preview_signals(self) -> None:
        """Podłącz sygnały podglądu — tylko gdy zakładka posiada podgląd.

        W trybie współdzielonym sygnały podglądu podłącza MainWindow (raz).
        """
        s = self.signals
        s.sig_preview_frame_ready.connect(self.video_preview.on_frame_ready)
        s.sig_bboxes_ready.connect(self.video_preview.set_bboxes)
        s.sig_video_duration_ready.connect(self.video_preview.on_duration_ready)
        s.sig_seek_position.connect(self.video_preview._on_seek_position)
        s.sig_cut_region_added.connect(self.video_preview._on_cut_region_changed)
        s.sig_cut_region_removed.connect(self.video_preview._on_cut_region_changed)
        s.sig_cut_regions_cleared.connect(self.video_preview._on_cut_region_changed)

    def set_controller(self, controller: object) -> None:
        """Ustaw referencję do kontrolera (wywoływane z MainWindow)."""
        self._controller = controller
        if self._owns_preview:
            self.video_preview.set_controller(controller)

    # ═════════════════════════════════════════════════════════════════════
    # Wspólny rozmiar podglądu (ten sam co w Projekcie)
    # ═════════════════════════════════════════════════════════════════════

    def showEvent(self, event) -> None:
        """Po pokazaniu zakładki przelicz wspólny rozmiar podglądu (16:9)."""
        super().showEvent(event)
        self._update_preview_size()

    def resizeEvent(self, event) -> None:
        """Przy każdej zmianie rozmiaru przelicz wspólny rozmiar podglądu."""
        super().resizeEvent(event)
        self._update_preview_size()

    def _update_preview_size(self) -> None:
        """Ustaw wspólny rozmiar podglądu 16:9 — identyczny jak w Projekcie.

        Używa tej samej funkcji co ProjectTab (wysokość = ~80% zakładki,
        szerokość 16:9 ograniczona do ~70% szerokości zakładki), więc podgląd
        (współdzielony widget) ma ten sam rozmiar w obu zakładkach.
        """
        total_w = self.width()
        total_h = self.height()
        if total_w < 100 or total_h < 100:
            return
        preview_w, preview_h = preview_aspect_size(total_h, total_w)
        self.preview_slot.setFixedSize(preview_w, preview_h)

    # ═════════════════════════════════════════════════════════════════════
    # Zakres eksportu IN/OUT
    # ═════════════════════════════════════════════════════════════════════

    def _fmt_time(self, secs: float) -> str:
        secs = max(0, int(secs))
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _duration_s(self) -> float:
        if self._controller is None:
            return 0.0
        return float(getattr(self._controller, "video_duration_s", 0.0) or 0.0)

    def _current_orig_pos(self) -> float:
        """Aktualna pozycja odtwarzania w oryginalnym czasie (po cięciach)."""
        sb = self.video_preview.seek_bar
        return sb.eff_to_orig(sb.get_position())

    def _on_set_in(self) -> None:
        """Ustaw punkt IN na aktualnej pozycji (ucina wszystko przed IN)."""
        dur = self._duration_s()
        if dur <= 0:
            return
        pos = min(max(0.0, self._current_orig_pos()), dur)
        if self._in_orig is not None and self._in_orig > 0:
            self._remove_boundary(0.0, self._in_orig)
        self._in_orig = pos
        if pos > 0:
            self._add_boundary(0.0, pos)
        if self._out_orig is not None and self._out_orig <= pos:
            self._clear_range()
            return
        self._update_inout_labels()

    def _on_set_out(self) -> None:
        """Ustaw punkt OUT na aktualnej pozycji (ucina wszystko po OUT)."""
        dur = self._duration_s()
        if dur <= 0:
            return
        pos = min(max(0.0, self._current_orig_pos()), dur)
        if self._out_orig is not None and self._out_orig < dur:
            self._remove_boundary(self._out_orig, dur)
        self._out_orig = pos
        if pos < dur:
            self._add_boundary(pos, dur)
        if self._in_orig is not None and self._in_orig >= pos:
            self._clear_range()
            return
        self._update_inout_labels()

    def _add_boundary(self, a: float, b: float) -> None:
        if self._controller is None or b <= a:
            return
        if hasattr(self._controller, "add_cut_region"):
            self._controller.add_cut_region(a, b)
        if (a, b) not in self._boundary_regions:
            self._boundary_regions.append((a, b))

    def _remove_boundary(self, a: float, b: float) -> None:
        if self._controller is not None and hasattr(self._controller, "remove_cut_region"):
            self._controller.remove_cut_region(a, b)
        if (a, b) in self._boundary_regions:
            self._boundary_regions.remove((a, b))

    def _clear_range(self) -> None:
        """Usuń graniczne cięcia IN/OUT i zresetuj stan zakresu."""
        for a, b in list(self._boundary_regions):
            self._remove_boundary(a, b)
        self._boundary_regions.clear()
        self._in_orig = None
        self._out_orig = None
        self._update_inout_labels()

    def _on_clear_range(self) -> None:
        self._clear_range()

    def _update_inout_labels(self) -> None:
        if self._in_orig is not None:
            self.lbl_in.setText(f"IN: {self._fmt_time(self._in_orig)}")
        else:
            self.lbl_in.setText("IN: --:--")
        if self._out_orig is not None:
            self.lbl_out.setText(f"OUT: {self._fmt_time(self._out_orig)}")
        else:
            self.lbl_out.setText("OUT: --:--")
        if self._in_orig is not None and self._out_orig is not None:
            self.lbl_range_len.setText(
                f"Zakres: {self._fmt_time(self._out_orig - self._in_orig)}"
            )
        else:
            self.lbl_range_len.setText("Zakres: --:--")

    def _on_video_duration_ready(self, _duration: float) -> None:
        """Nowy film — zresetuj zakres IN/OUT (nowa oś czasu)."""
        self._clear_range()

    def _ensure_range_applied(self) -> None:
        """Upewnij się, że zakres IN/OUT jest odzwierciedlony w cut_regions."""
        if self._controller is None:
            return
        dur = self._duration_s()
        a = self._in_orig if self._in_orig is not None else 0.0
        b = self._out_orig if self._out_orig is not None else dur
        for ra, rb in list(self._boundary_regions):
            self._remove_boundary(ra, rb)
        self._boundary_regions.clear()
        if a > 0:
            self._add_boundary(0.0, a)
        if b < dur:
            self._add_boundary(b, dur)

    # ═════════════════════════════════════════════════════════════════════
    # Eksport
    # ═════════════════════════════════════════════════════════════════════

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
        # Zakres IN/OUT jako cięcia graniczne — istniejący backend
        # (RenderMixin) odczytuje je z controller._cut_regions.
        self._ensure_range_applied()
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
        self._reset_ui()
        self.lbl_stats.setText(f"Błąd: {msg}")

    def _reset_ui(self) -> None:
        self.btn_render.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
