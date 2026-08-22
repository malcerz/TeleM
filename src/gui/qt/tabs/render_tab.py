"""Zakładka Rendering — podgląd HUD (bez filmu) + opcje eksportu + realny progress.

Układ:
- LEWO: HUD Preview (podgląd samej nakładki, czarne tło, bez filmu); gdy
  zakładka nie renderuje, w tym miejscu widoczny jest współdzielony podgląd
  wideo (do wyboru zakresu IN/OUT).
- PRAWO: Ustawienia eksportu + przycisk [ EKSPORTUJ ] + Anuluj.
- DÓŁ: rzeczywisty pasek postępu + statystyki (Frame/%/FPS/Elapsed/ETA/Status).

Progress bazuje na RZECZYWISTYCH ukończonych klatkach pipeline'u (kontrakt
on_render_progress: completed/total), NIE na timerze ani czasie źródła.
HUD Preview aktualizowany maksymalnie 1×/s (latest-state, bez GPU readback,
bez backpressure) — renderowany w wątku GUI, poza pętlą eksportera.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QComboBox,
    QLineEdit, QPushButton, QProgressBar, QLabel, QFileDialog, QMessageBox,
    QScrollArea, QFrame, QSizePolicy, QCheckBox,
)
from PIL import Image

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
        # Stan renderingu / HUD preview (latest-state, ~5 Hz)
        self._rendering = False
        self._cancelling = False
        self._render_start = 0.0
        self._render_total = 0
        self._hud_ts: float | None = None
        self._hud_chart_data = None
        self._hud_prepare_cache: dict | None = None
        self._last_preview_time = 0.0
        self._preview_busy = False
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

        # ── Poziom główny: LEWO podgląd / PRAWO opcje+eksport ────────────
        main = QHBoxLayout()
        main.setSpacing(8)

        # LEWY: HUD Preview (podczas renderingu) / wideo IN/OUT (idle)
        self.left_panel = QWidget()
        self.left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # HUD Preview widget (czarne tło, bez filmu) — domyślnie ukryty
        self.hud_preview_label = QLabel("Renderowanie...")
        self.hud_preview_label.setAlignment(Qt.AlignCenter)
        self.hud_preview_label.setStyleSheet(
            "QLabel { background-color: #000000; color: #888; "
            "border: 1px solid #333; font-size: 15px; }"
        )
        self.hud_preview_label.setVisible(False)
        left_layout.addWidget(self.hud_preview_label, 0, Qt.AlignHCenter)

        # Współdzielony podgląd wideo (zakres IN/OUT — tryb idle)
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

        main.addWidget(self.left_panel, 3)  # ~75%

        # PRAWY: Ustawienia eksportu + przycisk Eksportuj pod nimi
        self.right_panel = QWidget()
        self.right_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.right_panel.setMinimumWidth(280)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        group = QGroupBox("Ustawienia eksportu")
        group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        form = QFormLayout(group)
        form.setSpacing(10)

        self.cmb_encoder = QComboBox()
        self.cmb_encoder.addItems(["amd", "nv", "intel", "cpu"])
        self.cmb_encoder.setToolTip("amd = AMD AMF (domyślny), nv = NVIDIA NVENC, intel = Intel QuickSync, cpu = software")
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

        # HUD Preview podczas renderowania (default ON; odświeżanie 1 Hz)
        self.chk_hud_preview = QCheckBox("Podgląd HUD podczas renderowania")
        self.chk_hud_preview.setChecked(True)
        self.chk_hud_preview.setToolTip(
            "Bez filmu, czarne tło, aktualizacja maksymalnie 1×/s. "
            "Nie ma wpływu na finalny rendering.")
        form.addRow(self.chk_hud_preview)

        # Scroll — opcje mieszczą się w 25% nawet przy małym oknie
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(group)
        right_layout.addWidget(scroll, 1)

        # Przycisk eksportu pod ustawieniami (prawa strona)
        self.btn_render = QPushButton("EKSPORTUJ")
        self.btn_render.setMinimumHeight(48)
        self.btn_render.setStyleSheet(
            "QPushButton { background-color: #d44000; color: white; "
            "font-size: 14px; font-weight: bold; border: none; "
            "border-radius: 4px; padding: 8px 24px; }"
            "QPushButton:hover { background-color: #e45010; }"
            "QPushButton:disabled { background-color: #555; }"
        )
        self.btn_render.clicked.connect(self._on_render)
        right_layout.addWidget(self.btn_render)

        self.btn_cancel = QPushButton("Anuluj")
        self.btn_cancel.setMinimumHeight(32)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        right_layout.addWidget(self.btn_cancel)

        main.addWidget(self.right_panel, 1)  # ~25%

        vbox.addLayout(main, 1)

        # ── Dół: pasek postępu + statystyki ──────────────────────────────
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        # Grubszy, czytelny pasek (tylko prezentacja; logika bez zmian)
        self.progress.setMinimumHeight(10)
        self.progress.setStyleSheet(
            "QProgressBar { min-height: 10px; border: 1px solid #999; "
            "border-radius: 5px; background: #eee; text-align: center; }"
            "QProgressBar::chunk { background-color: #2e8b57; "
            "border-radius: 5px; }"
        )
        vbox.addWidget(self.progress)

        # Statystyki: tworzone RAZ, jedna linia, czarny tekst, stała
        # wysokość (bez re-layoutu / migania podczas aktualizacji).
        self.lbl_stats = QLabel("Gotowy")
        self.lbl_stats.setStyleSheet("QLabel { color: black; font-size: 12px; }")
        self.lbl_stats.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_stats.setWordWrap(False)
        self.lbl_stats.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vbox.addWidget(self.lbl_stats)

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
        s.sig_render_progress.connect(self._on_render_progress)
        s.sig_export_preview_ready.connect(self._on_export_preview_ready)
        s.sig_render_finished.connect(self._on_finished)
        s.sig_render_stopped.connect(self._on_stopped)
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
        if self._rendering or self._cancelling:
            return
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
        # Rozpoczęcie: disable, progress=0, HUD Preview włączony
        self._rendering = True
        self._cancelling = False
        self._render_start = time.monotonic()
        self._render_total = 0
        self._hud_ts = None
        self._hud_chart_data = None
        self._hud_prepare_cache = None
        self.btn_render.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_stats(0, 0, 0.0, 0.0, "Renderowanie...")
        # Przełącz widok na HUD Preview (bez filmu) — wideo wraca po końcu
        hud_on = self.chk_hud_preview.isChecked()
        self.preview_slot.setVisible(not hud_on)
        self.hud_preview_label.setVisible(hud_on)
        self.hud_preview_label.setText("Renderowanie...")
        self.signals.sig_render_requested.emit(options)

    def _on_cancel(self) -> None:
        if not self._rendering or self._cancelling:
            return
        # P1-B FIX: CANCELLING state. Do NOT call _end_render() here.
        # Wait for worker thread to confirm exit via sig_render_stopped / sig_error.
        self._cancelling = True
        self.btn_render.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self._set_stats(
            self.progress.value(), self._render_total,
            time.monotonic() - self._render_start if self._render_start else 0.0,
            0.0, "Anulowanie...",
        )
        self.signals.sig_render_cancelled.emit()

    def _on_stopped(self) -> None:
        """Potwierdzenie zakończenia workera po anulowaniu -> powrót do IDLE."""
        self._set_stats(
            self.progress.value(), self._render_total,
            time.monotonic() - self._render_start if self._render_start else 0.0,
            0.0, "Anulowano",
        )
        self._end_render()

    def _on_progress(self, _percent: int, _text: str) -> None:
        # Legacy progress_cb — NIE ustawia już tekstu statystyk.
        # Jedyny źródło tekstu to _set_stats (przez sig_render_progress);
        # ustawianie go tutaj dawało 2× setText na event (tekst eksportera
        # 1-liniowy + 6-liniowy format) → miganie QLabel / reflow layoutu.
        return

    def _on_render_progress(self, completed: int, total: int, elapsed: float,
                            fps: float, hud_state) -> None:
        """Rzeczywisty progress pipeline'u (completed/total, nie timer)."""
        if self._cancelling:
            return
        if total > 0:
            self._render_total = total
        total = self._render_total or total or 1
        pct = (completed / total) * 100.0
        # Nigdy nie pokazuj 100% przed faktycznym końcem (finalizacja/mux).
        if completed >= total:
            pct = min(pct, 99.0)
            status = "Finalizacja..."
        else:
            status = "Renderowanie..."
        self.progress.setValue(int(pct))
        self._set_stats(completed, total, elapsed, fps, status)

        # HUD Preview — latest-state, z wideo, tylko gdy backend dostarczył snapshot
        if hud_state is not None and isinstance(hud_state, dict) and self.chk_hud_preview.isChecked():
            self._hud_ts = hud_state.get("ts")
            now = time.monotonic()
            if now - self._last_preview_time >= 0.2:  # ~5 Hz
                self._last_preview_time = now
                self._trigger_async_preview(self._hud_ts)

    def _set_stats(self, completed: int, total: int, elapsed: float, fps: float,
                   status: str, final_eta: str | None = None) -> None:
        total = max(total, 0)
        if total and completed >= 0:
            pct = (completed / total) * 100.0
            frame_txt = f"{completed} / {total}"
            pct_txt = f"{pct:.1f}%"
        else:
            frame_txt = "--"
            pct_txt = "--"
        if final_eta is not None:
            eta_txt = final_eta
        elif fps > 0 and total and completed < total:
            eta = (total - completed) / fps
            eta_txt = self._fmt_time(eta)
        else:
            eta_txt = "--:--"
        elapsed_txt = self._fmt_time(elapsed) if elapsed > 0 else "--:--"
        fps_txt = f"{fps:.1f}" if fps > 0 else "--"
        # Jedna linia — bez newline, bez łamania; stała wysokość labela
        # (Fixed + wordWrap=False) → brak przeskakiwania layoutu.
        self.lbl_stats.setText(
            f"Frame: {frame_txt}   |   {pct_txt}   |   FPS: {fps_txt}"
            f"   |   Czas: {elapsed_txt}   |   ETA: {eta_txt}"
            f"   |   {status}"
        )

    def _on_finished(self, _stats: dict, output: str) -> None:
        # Koniec — dopiero teraz 100% i status "Gotowe"
        self.progress.setValue(100)
        elapsed = time.monotonic() - self._render_start if self._render_start else 0.0
        fps = (self._render_total / elapsed) if elapsed > 0 and self._render_total else 0.0
        self._set_stats(self._render_total, self._render_total, elapsed, fps,
                        "Gotowe", final_eta="00:00")
        self._end_render()
        QMessageBox.information(
            self, "Eksport zakończony",
            f"Plik zapisany:\n{output}",
        )

    def _on_error(self, msg: str) -> None:
        self._set_stats(
            self.progress.value(), self._render_total,
            time.monotonic() - self._render_start if self._render_start else 0.0,
            0.0, f"Błąd: {msg}",
        )
        self._end_render()

    def _end_render(self) -> None:
        """Powrót do stanu idle po zakończeniu / anulowaniu / błędzie."""
        self._rendering = False
        self._cancelling = False
        self.btn_render.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        # Wróć do podglądu wideo (IN/OUT)
        self.hud_preview_label.setVisible(False)
        self.preview_slot.setVisible(True)
        self._update_preview_size()
        self._hud_ts = None
        self._last_preview_time = 0.0

    def _update_preview_size(self) -> None:
        """Ustaw wspólny rozmiar 16:9 dla podglądu wideo i HUD Preview."""
        total_w = self.width()
        total_h = self.height()
        if total_w < 100 or total_h < 100:
            return
        preview_w, preview_h = preview_aspect_size(total_h, total_w)
        self.preview_slot.setFixedSize(preview_w, preview_h)
        self.hud_preview_label.setFixedSize(preview_w, preview_h)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_preview_size()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_preview_size()

    # ═════════════════════════════════════════════════════════════════════
    # HUD Preview — renderowany w wątku GUI, 1 Hz, bez GPU readback
    # ═════════════════════════════════════════════════════════════════════

    def _build_hud_prepare_cache(self) -> None:
        """Wartości zakresów (const dla całego wideo) — jak PreviewMixin."""
        ctrl = self._controller
        telemetry = getattr(ctrl, "telemetry", None)
        if telemetry is None:
            self._hud_prepare_cache = {}
            return
        layout = getattr(ctrl, "layout", {}) or {}
        indic = layout.get("indicators", {})
        spd = list(telemetry.speed_samples or [])
        trk = list(telemetry.track_samples or [])
        alt = list(telemetry.alt_samples or [])
        gpx_spd = list(telemetry.gpx_speed_samples or [])
        gpx_trk = list(telemetry.gpx_track_samples or [])
        gpx_alt = list(telemetry.gpx_alt_samples or [])
        fit_data = dict(telemetry.fit_data or {})
        max_dist = None
        src = indic.get("dist_visual", {}).get("source", "gpmf")
        cand = (gpx_trk or trk) if src == "gpx" else (fit_data.get("track", []) or trk if src == "fit" else trk)
        if cand:
            max_dist = cand[-1][1]
        max_spd = None
        src = indic.get("speed_visual", {}).get("source", "gpmf")
        cand = (gpx_spd or spd) if src == "gpx" else (fit_data.get("speed", []) or spd if src == "fit" else spd)
        if cand:
            vals = [s for _, s in cand]
            if vals:
                max_spd = max(vals)
        min_a = max_a = None
        src = indic.get("alt_visual", {}).get("source", "gpmf")
        cand = (gpx_alt or alt) if src == "gpx" else (fit_data.get("alt", []) or alt if src == "fit" else alt)
        if cand:
            alts = [a for _, a in cand]
            if alts:
                min_a, max_a = min(alts), max(alts)
        self._hud_prepare_cache = {
            "max_distance_m": max_dist,
            "max_speed_kmh": max_spd,
            "min_alt": min_a,
            "max_alt": max_a,
        }

    def _on_export_preview_ready(self, qimg: QImage) -> None:
        """Odbiera wyrenderowaną klatkę podglądu w głównym wątku GUI."""
        if not self._rendering or self._cancelling or qimg is None:
            return
        pix = QPixmap.fromImage(qimg)
        self.hud_preview_label.setPixmap(
            pix.scaled(self.hud_preview_label.size(),
                       Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _trigger_async_preview(self, ts: float) -> None:
        """Uruchamia asynchroniczny render klatki podglądu w tle (zero backpressure)."""
        if not self._rendering or self._cancelling or self._controller is None:
            return
        if self._preview_busy:
            return
        self._preview_busy = True

        tw = self.hud_preview_label.width() if self.hud_preview_label.width() > 100 else 640
        layout = getattr(self._controller, "layout", None) or {}
        lw = int(layout.get("width", 1920) or 1920)
        lh = int(layout.get("height", 1080) or 1080)
        th = max(1, int(tw * lh / lw)) if lw > 0 else int(tw * 9 / 16)

        def worker():
            try:
                qimg = self._build_preview_qimage(ts, tw, th)
                if qimg is not None and self._rendering and not self._cancelling:
                    self.signals.sig_export_preview_ready.emit(qimg)
            finally:
                self._preview_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _build_preview_qimage(self, ts: float, tw: int, th: int) -> QImage | None:
        """Renderuje klatkę wideo + HUD overlay do QImage (background thread)."""
        try:
            from src.overlay_renderer import prepare_overlay_frame_data, build_chart_data, render_preview
            ctrl = self._controller
            telemetry = getattr(ctrl, "telemetry", None)
            layout = getattr(ctrl, "layout", None)
            if telemetry is None or layout is None or not getattr(telemetry, "start_dt_utc", None):
                return None
            if self._hud_chart_data is None:
                video_dur_tmp = float(getattr(ctrl, "video_duration_s", 0.0) or 0.0)
                end_dt_tmp = (telemetry.start_dt_utc + timedelta(seconds=video_dur_tmp)) if (telemetry.start_dt_utc and video_dur_tmp > 0) else None
                source_ranges_tmp = {}
                if getattr(telemetry, "fit_data", None):
                    all_fit_pts = [s for s in telemetry.fit_data.values() if s]
                    if all_fit_pts:
                        source_ranges_tmp["fit"] = (
                            min(s[0][0] for s in all_fit_pts),
                            max(s[-1][0] for s in all_fit_pts),
                        )
                self._hud_chart_data = build_chart_data(
                    layout, telemetry.get_samples_for_source, telemetry.resolve_samples,
                    start_dt_utc=telemetry.start_dt_utc, end_dt_utc=end_dt_tmp,
                    source_activity_ranges=source_ranges_tmp,
                )
            if self._hud_prepare_cache is None:
                self._build_hud_prepare_cache()

            # Wczytaj klatkę wideo odpowiadającą aktualnemu czasowi eksportu
            base = None
            last_src = getattr(ctrl, "last_src_pil", None) or getattr(ctrl, "src_img", None)
            if last_src is not None:
                try:
                    base = last_src.convert("RGBA").resize((tw, th), Image.Resampling.BILINEAR)
                except Exception:
                    base = None

            if base is None:
                try:
                    from src.video_helpers import extract_frame
                    v_paths = getattr(ctrl, "video_paths", None) or [getattr(ctrl, "video_path", None)]
                    if v_paths and v_paths[0]:
                        frame = extract_frame(
                            v_paths,
                            ts,
                            ffmpeg_exe=getattr(ctrl, "ffmpeg_exe", "ffmpeg") or "ffmpeg",
                            ffprobe_exe=getattr(ctrl, "ffprobe_exe", "ffprobe") or "ffprobe",
                            target_w=tw,
                        )
                        if frame:
                            base = frame.convert("RGBA").resize((tw, th), Image.Resampling.BILINEAR)
                except Exception:
                    base = None

            if base is None:
                base = Image.new("RGBA", (tw, th), (0, 0, 0, 255))

            start_dt = telemetry.start_dt_utc
            if isinstance(start_dt, datetime):
                target_dt = start_dt + timedelta(seconds=ts)
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=timezone.utc)
            elif isinstance(start_dt, (int, float)):
                target_dt = datetime.fromtimestamp(float(start_dt) + ts, tz=timezone.utc)
            else:
                target_dt = datetime.now(timezone.utc)

            video_dur = float(getattr(ctrl, "video_duration_s", 0.0) or 0.0)
            overlay_data = prepare_overlay_frame_data(
                layout=layout,
                target_dt=target_dt,
                tz_offset_hours=2,
                start_dt_utc=telemetry.start_dt_utc,
                speed_samples=telemetry.speed_samples or [],
                track_samples=telemetry.track_samples or [],
                alt_samples=telemetry.alt_samples or [],
                iso_samples=telemetry.iso_samples,
                exposure_samples=telemetry.exposure_samples,
                temperature_samples=telemetry.temperature_samples,
                gpx_speed_samples=telemetry.gpx_speed_samples,
                gpx_track_samples=telemetry.gpx_track_samples,
                gpx_alt_samples=telemetry.gpx_alt_samples,
                gpx_power_samples=telemetry.gpx_power_samples,
                gpx_atemp_samples=telemetry.gpx_atemp_samples,
                gpx_hr_samples=telemetry.gpx_hr_samples,
                gpx_cad_samples=telemetry.gpx_cad_samples,
                fit_data=telemetry.fit_data,
                gps_track=telemetry.get_gps_track_for_source(
                    layout.get("indicators", {}).get("track_map", {}).get("source", "fit")),
                total_frames=max(1, int(video_dur)),
                current_index=int(ts) if ts else 0,
                chart_data=self._hud_chart_data,
                extra_field_keys=getattr(ctrl, "fit_ext_fields", None),
                resolve_cache_value=lambda k, src, dt, indicator_key=None: telemetry.resolve_value(
                    k, dt, source=src, indicator_key=indicator_key
                ),
                _range_cache=self._hud_prepare_cache,
            )
            if not overlay_data:
                return None
            preview = render_preview(
                base, layout, getattr(ctrl, "font_path", None),
                overlay_data["date_text"], overlay_data["time_text"],
                overlay_data["speed_value"],
                overlay_data["distance_m"],
                overlay_data["max_distance_m"],
                overlay_data["alt_value"],
                overlay_data["min_alt"],
                overlay_data["max_alt"],
                overlay_data["iso_value"],
                overlay_data["exposure_value"],
                overlay_data["temp_value"],
                indicator_values=overlay_data["indicator_values"],
                max_speed_kmh=overlay_data["max_speed_kmh"],
                power_value=overlay_data["power_value"],
                atemp_value=overlay_data["atemp_value"],
                hr_value=overlay_data["hr_value"],
                cad_value=overlay_data["cad_value"],
                battery_value=overlay_data["battery_value"],
                _bboxes={},
                extra_indicators=overlay_data["extra_indicators"],
                chart_data=overlay_data["chart_data"],
                current_position=(ts / max(1.0, video_dur)) if video_dur > 0 else 0.0,
                gps_track=overlay_data["gps_track"],
                map_heading=overlay_data.get("map_heading"),
                target_dt=overlay_data["target_dt"],
                start_dt_utc=overlay_data["start_dt_utc"],
                elapsed_seconds=overlay_data["elapsed_seconds"],
                avg_speed_kmh=overlay_data["avg_speed_kmh"],
                inplace=False,
            )
            rgba = preview.convert("RGBA")
            data = rgba.tobytes("raw", "RGBA")
            qimg = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888).copy()
            return qimg
        except Exception as exc:  # noqa: BLE001
            print(f"[Export Preview Async] {exc}", flush=True)
            return None
