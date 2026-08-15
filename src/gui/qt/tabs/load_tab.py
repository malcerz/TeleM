"""Zakładka Wczytywanie — wybór plików MP4, GPX, FIT."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QPushButton,
    QLabel, QHBoxLayout, QFileDialog, QMessageBox, QComboBox,
)

from src.gui.qt.signals import get_signals
from src.gui.qt.mpv_hwdec import detect_preview_vendor, get_available_vendors, vendor_label
from src.gui.qt.mp4_inspector import (
    inspect_mp4,
    resolve_ffprobe,
    format_file_info_text,
    QP_PLACEHOLDER,
)


class LoadTab(QWidget):
    """Zakładka wyboru plików źródłowych."""

    # Wyniki asynchronicznej inspekcji pliku (worker → GUI, wątek główny)
    sig_file_info_ready = Signal(dict, int)
    sig_file_info_error = Signal(str, int)
    # Wyniki asynchronicznej analizy QP
    sig_qp_progress = Signal(int, int)   # (percent, gen)
    sig_qp_done = Signal(dict, int)      # (info: dict, gen)
    sig_qp_error = Signal(str, int)      # (message, gen)

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._video_paths: list[str] = []
        self._gpx_path: str = ""
        self._fit_path: str = ""
        # Generacja inspekcji — pozwala zignorować wyniki dla poprzedniego pliku
        self._inspection_gen: int = 0
        # Stan analizy QP (token generacji + anulowanie)
        self._qp_gen: int = 0
        self._qp_path: str = ""
        self._qp_cancel_event: threading.Event | None = None
        self._build_ui()
        self._connect_local_signals()

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

        # ── Informacje o filmie (automatyczna inspekcja po wyborze MP4) ──
        info_group = QGroupBox("Informacje o filmie")
        info_group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        info_vbox = QVBoxLayout(info_group)
        info_vbox.setSpacing(8)

        self.lbl_file_info = QLabel("Wybierz plik MP4, aby zobaczyć informacje o filmie.")
        self.lbl_file_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.lbl_file_info.setWordWrap(True)
        self.lbl_file_info.setStyleSheet(
            "QLabel { color: #111111; font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; background-color: #ffffff; border: 1px solid #cccccc; "
            "border-radius: 4px; padding: 8px; }"
        )
        info_vbox.addWidget(self.lbl_file_info)

        # Przycisk Analiza QP + miejsce na wynik
        self.btn_analyze_qp = QPushButton("Analiza QP")
        self.btn_analyze_qp.setMinimumHeight(30)
        self.btn_analyze_qp.setEnabled(False)
        self.btn_analyze_qp.setToolTip(
            "Analiza rozkładu QP (średnia/mediana/min/max) — analiza zostanie "
            "uruchomiona po wskazaniu pliku MP4."
        )
        self.btn_analyze_qp.clicked.connect(self._on_analyze_qp)
        info_vbox.addWidget(self.btn_analyze_qp, alignment=Qt.AlignLeft)

        self.lbl_qp_result = QLabel(QP_PLACEHOLDER)
        self.lbl_qp_result.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.lbl_qp_result.setStyleSheet(
            "QLabel { color: #333333; font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; background-color: #ffffff; border: 1px solid #cccccc; "
            "border-radius: 4px; padding: 8px; }"
        )
        info_vbox.addWidget(self.lbl_qp_result)

        vbox.addWidget(info_group)

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
            # Natychmiastowa (asynchroniczna) inspekcja — bez naciskania Wczytaj
            self._start_info_inspection()

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
        # Unieważnij oczekującą inspekcję i zresetuj panel informacji
        self._inspection_gen += 1
        self.lbl_file_info.setText("Wybierz plik MP4, aby zobaczyć informacje o filmie.")
        self._reset_qp_state()
        self.btn_analyze_qp.setEnabled(False)

    # ═════════════════════════════════════════════════════════════════════
    # Asynchroniczna inspekcja pliku (ffprobe poza wątkiem GUI)
    # ═════════════════════════════════════════════════════════════════════

    def _connect_local_signals(self) -> None:
        self.sig_file_info_ready.connect(self._on_file_info_ready)
        self.sig_file_info_error.connect(self._on_file_info_error)
        self.sig_qp_progress.connect(self._on_qp_progress)
        self.sig_qp_done.connect(self._on_qp_done)
        self.sig_qp_error.connect(self._on_qp_error)

    def _start_info_inspection(self) -> None:
        """Uruchom odczyt informacji o pierwszym wybranym pliku MP4."""
        if not self._video_paths:
            return
        path = self._video_paths[0]
        self._inspection_gen += 1
        gen = self._inspection_gen
        self.lbl_file_info.setText("Odczytywanie informacji o filmie...")
        self.btn_analyze_qp.setEnabled(True)
        # Nowy plik — unieważnij/zatrzymaj ewentualną analizę QP poprzedniego
        self._reset_qp_state()

        def worker() -> None:
            try:
                ffprobe = resolve_ffprobe()
                info = inspect_mp4(path, ffprobe)
                self.sig_file_info_ready.emit(info, gen)
            except Exception:
                # Nie ujawniamy szczegółów błędu w GUI — tylko komunikat ogólny
                self.sig_file_info_error.emit(str(Path(path).name), gen)

        threading.Thread(target=worker, daemon=True).start()

    def _on_file_info_ready(self, info: dict, gen: int) -> None:
        if gen != self._inspection_gen:
            return  # wybrano już inny plik — zignoruj wynik
        self.lbl_file_info.setText(format_file_info_text(info))

    def _on_file_info_error(self, _name: str, gen: int) -> None:
        if gen != self._inspection_gen:
            return
        self.lbl_file_info.setText("Nie udało się odczytać informacji o filmie.")

    # ═════════════════════════════════════════════════════════════════════
    # Analiza QP — rzeczywista, asynchroniczna (src/qp_analyzer)
    # ═════════════════════════════════════════════════════════════════════

    def _on_analyze_qp(self) -> None:
        if not self._video_paths:
            return
        path = self._video_paths[0]
        # Jeśli analiza już trwa — kliknięcie anuluje
        if self._qp_cancel_event is not None:
            self._qp_cancel_event.set()
            return
        if not Path(path).exists():
            self._show_qp_error("Plik nie istnieje.")
            return
        self.analyze_qp(path)

    def analyze_qp(self, video_path: str) -> None:
        """Uruchom rzeczywistą analizę QP poza wątkiem GUI."""
        self._qp_gen += 1
        gen = self._qp_gen
        self._qp_path = video_path
        self._qp_cancel_event = threading.Event()
        self.btn_analyze_qp.setText("Anuluj analizę QP")
        self.lbl_qp_result.setText(QP_PLACEHOLDER + "\n\nAnaliza QP: 0%")

        def worker() -> None:
            try:
                from src.qp_analyzer import analyze_qp as run_qp
                result = run_qp(
                    video_path,
                    progress_cb=lambda pct, _frames: self.sig_qp_progress.emit(pct, gen),
                    cancel_event=self._qp_cancel_event,
                )
                self.sig_qp_done.emit({
                    "ok": result.ok,
                    "error": result.error,
                    "avg": result.avg,
                    "median": result.median,
                    "minimum": result.minimum,
                    "maximum": result.maximum,
                    "frames": result.frames,
                    "samples": result.samples,
                    "elapsed_s": result.elapsed_s,
                }, gen)
            except Exception as e:
                self.sig_qp_error.emit(str(e), gen)

        threading.Thread(target=worker, daemon=True).start()

    def _on_qp_progress(self, pct: int, gen: int) -> None:
        if gen != self._qp_gen:
            return
        self.lbl_qp_result.setText(QP_PLACEHOLDER + f"\n\nAnaliza QP: {pct}%")

    def _on_qp_done(self, info: dict, gen: int) -> None:
        if gen != self._qp_gen:
            return
        self._qp_cancel_event = None
        self.btn_analyze_qp.setText("Analiza QP")
        if not info.get("ok"):
            self._show_qp_error(info.get("error") or "Nie udało się odczytać QP.")
            return
        avg = f"{info['avg']:.2f}" if info.get("avg") is not None else "—"
        med = str(info["median"]) if info.get("median") is not None else "—"
        mn = str(info["minimum"]) if info.get("minimum") is not None else "—"
        mx = str(info["maximum"]) if info.get("maximum") is not None else "—"
        self.lbl_qp_result.setText(
            "Analiza QP\n\n"
            f"Średni:   {avg}\n"
            f"Mediana:  {med}\n"
            f"Min:      {mn}\n"
            f"Max:      {mx}\n\n"
            f"Przeanalizowano: {info.get('frames', 0)} klatek\n"
            f"Czas analizy: {info.get('elapsed_s', 0.0):.1f} s\n"
            f"Próbki QP: {info.get('samples', 0)}"
        )

    def _on_qp_error(self, msg: str, gen: int) -> None:
        if gen != self._qp_gen:
            return
        self._qp_cancel_event = None
        self.btn_analyze_qp.setText("Analiza QP")
        self._show_qp_error(msg)

    def _show_qp_error(self, msg: str) -> None:
        self.lbl_qp_result.setText(
            QP_PLACEHOLDER + "\n\nNie udało się odczytać QP dla tego strumienia.\n" + msg
        )

    def _reset_qp_state(self) -> None:
        """Zatrzymaj trwającą analizę QP i zresetuj panel wyniku."""
        self._qp_gen += 1
        if self._qp_cancel_event is not None:
            self._qp_cancel_event.set()
        self._qp_cancel_event = None
        self._qp_path = ""
        self.btn_analyze_qp.setText("Analiza QP")
        self.lbl_qp_result.setText(QP_PLACEHOLDER)
