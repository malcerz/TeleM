"""Zakładka Wczytywanie — wybór plików MP4, GPX, FIT oraz diagnostyka sprzętu."""

from __future__ import annotations

import json
import os
import time
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QPushButton,
    QLabel, QHBoxLayout, QFileDialog, QMessageBox, QComboBox, QProgressBar,
    QScrollArea, QFrame, QGridLayout, QSizePolicy,
)

from src.gui.qt.signals import get_signals
from src.gui.qt.mpv_hwdec import detect_preview_vendor, get_available_vendors, vendor_label
from src.gui.qt.mp4_inspector import (
    inspect_mp4,
    resolve_ffprobe,
    format_file_info_text,
    QP_PLACEHOLDER,
)
from src.gui.qt.hardware_info import HardwareCapabilitiesInfo, get_hardware_info


class HardwareInfoWidget(QGroupBox):
    """Panel informacyjny prezentujący możliwości sprzętowe systemu (tylko do odczytu)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Możliwości sprzętu", parent)
        self.setStyleSheet(
            "QGroupBox { font-size: 13px; font-weight: bold; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        info = get_hardware_info()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setSpacing(5)
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        def _val_lbl(text: str, bold: bool = False, color: str = "#111111") -> QLabel:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            weight = "bold" if bold else "normal"
            lbl.setStyleSheet(
                f"color: {color}; font-size: 11px; font-weight: {weight}; "
                "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"
            )
            return lbl

        def _key_lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #666666; font-size: 11px; font-weight: bold;")
            return lbl

        # System & CPU
        form.addRow(_key_lbl("System:"), _val_lbl(info.os_name))
        form.addRow(_key_lbl("Procesor:"), _val_lbl(f"{info.cpu_name} ({info.cpu_threads})"))
        form.addRow(_key_lbl("Pamięć RAM:"), _val_lbl(info.ram_total, bold=True))

        # GPU
        gpu_str = "\n".join(info.gpus) if info.gpus else "Nieznana"
        form.addRow(_key_lbl("Karta graficzna:"), _val_lbl(gpu_str))
        form.addRow(_key_lbl("Podgląd:"), _val_lbl(info.active_preview))

        # Enkodery
        enc_summary = (
            f"AMD: {info.enc_amd}\n"
            f"NVIDIA: {info.enc_nvidia}  |  Intel: {info.enc_intel}\n"
            f"CPU: {info.enc_cpu}"
        )
        form.addRow(_key_lbl("Kodowanie:"), _val_lbl(enc_summary))

        # Dekodery
        dec_summary = (
            f"H.264: {info.dec_h264}\n"
            f"HEVC: {info.dec_hevc}\n"
            f"AV1: {info.dec_av1}"
        )
        form.addRow(_key_lbl("Dekodowanie:"), _val_lbl(dec_summary))

        # Maks. rozdzielczość
        max_summary = f"Dekoder: {info.max_decode}\nEnkoder: {info.max_encode}"
        form.addRow(_key_lbl("Maks. rozdz.:"), _val_lbl(max_summary))

        layout.addLayout(form)


class VideoFileCardWidget(QFrame):
    """Karta reprezentująca pojedynczy plik wideo z własnym zestawem parametrów technicznych."""

    sig_qp_clicked = Signal(str, int)  # (video_path, file_index)

    def __init__(self, index: int, video_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.file_index = index
        self.video_path = video_path
        self.metadata: dict[str, Any] = {}
        self._qp_active = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "VideoFileCardWidget { background-color: #ffffff; border: 1px solid #dcdcdc; "
            "border-radius: 6px; } "
            "VideoFileCardWidget:hover { border-color: #0078d4; }"
        )
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(10, 8, 10, 8)
        vbox.setSpacing(6)

        # ── Nagłówek karty ──
        header = QHBoxLayout()
        header.setSpacing(8)

        self.lbl_badge = QLabel(f"#{self.file_index + 1}")
        self.lbl_badge.setStyleSheet(
            "background-color: #0078d4; color: #ffffff; border-radius: 3px; "
            "padding: 2px 7px; font-weight: bold; font-size: 11px;"
        )
        header.addWidget(self.lbl_badge)

        self.lbl_filename = QLabel(Path(self.video_path).name)
        self.lbl_filename.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #111111; "
            "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"
        )
        header.addWidget(self.lbl_filename)

        header.addStretch()

        self.lbl_badges = QLabel("⏱ —  |  💾 —")
        self.lbl_badges.setStyleSheet(
            "color: #444444; font-size: 11px; background-color: #f1f3f4; "
            "border-radius: 3px; padding: 2px 6px;"
        )
        header.addWidget(self.lbl_badges)

        self.btn_card_qp = QPushButton("Analiza QP")
        self.btn_card_qp.setFixedHeight(24)
        self.btn_card_qp.setCursor(Qt.PointingHandCursor)
        self.btn_card_qp.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 10px; background-color: #f8f9fa; "
            "border: 1px solid #cccccc; border-radius: 3px; font-weight: bold; color: #333333; } "
            "QPushButton:hover { background-color: #e8f0fe; border-color: #1a73e8; color: #1a73e8; }"
        )
        self.btn_card_qp.clicked.connect(self._on_qp_clicked)
        header.addWidget(self.btn_card_qp)

        vbox.addLayout(header)

        # ── Siatka parametrów technicznych ──
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(3)
        self.grid.setContentsMargins(4, 2, 4, 2)

        def _field_lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet("font-size: 11px; color: #333333;")
            return lbl

        self.lbl_res = _field_lbl("<b>Rozdzielczość:</b> Odczytywanie...")
        self.lbl_fps = _field_lbl("<b>FPS:</b> —")
        self.lbl_codec = _field_lbl("<b>Kodek:</b> —")
        self.lbl_pixfmt = _field_lbl("<b>Format:</b> —")
        self.lbl_bitrate = _field_lbl("<b>Bitrate:</b> —")
        self.lbl_color = _field_lbl("<b>Kolor:</b> —")
        self.lbl_audio = _field_lbl("<b>Audio:</b> —")
        self.lbl_gpmf = _field_lbl("<b>GPMF:</b> —")

        # Row 0
        self.grid.addWidget(self.lbl_res, 0, 0)
        self.grid.addWidget(self.lbl_fps, 0, 1)
        self.grid.addWidget(self.lbl_codec, 0, 2)
        self.grid.addWidget(self.lbl_pixfmt, 0, 3)

        # Row 1
        self.grid.addWidget(self.lbl_bitrate, 1, 0)
        self.grid.addWidget(self.lbl_color, 1, 1)
        self.grid.addWidget(self.lbl_audio, 1, 2)
        self.grid.addWidget(self.lbl_gpmf, 1, 3)

        vbox.addLayout(self.grid)

        # ── Wiersz telemetrii (FIT / GPX) ──
        self.lbl_telem = QLabel("<b>FIT / GPX:</b> <span style='color:#666;'>Brak (auto / manualny)</span>")
        self.lbl_telem.setTextFormat(Qt.RichText)
        self.lbl_telem.setStyleSheet("font-size: 11px; color: #333333; padding-left: 4px;")
        vbox.addWidget(self.lbl_telem)

        # ── Wiersz wyniku QP (zwijany) ──
        self.lbl_qp_info = QLabel("")
        self.lbl_qp_info.setTextFormat(Qt.RichText)
        self.lbl_qp_info.setWordWrap(True)
        self.lbl_qp_info.setVisible(False)
        self.lbl_qp_info.setStyleSheet(
            "QLabel { background-color: #f1f8ff; border: 1px solid #c8e1ff; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; color: #0366d6; }"
        )
        vbox.addWidget(self.lbl_qp_info)

    def _on_qp_clicked(self) -> None:
        self.sig_qp_clicked.emit(self.video_path, self.file_index)

    def update_info(self, info: dict[str, Any], paired_telemetry: str = "") -> None:
        self.metadata = dict(info)
        v = info.get("video") or {}
        c = info.get("color") or {}
        a = info.get("audio")

        dur = info.get("duration_text") or "—"
        sz = info.get("size_text") or "—"
        self.lbl_badges.setText(f"⏱ {dur}  |  💾 {sz}")

        res = v.get("resolution") or "—"
        self.lbl_res.setText(f"<b>Rozdzielczość:</b> <span style='color:#0078d4; font-weight:bold;'>{res}</span>")
        self.lbl_fps.setText(f"<b>FPS:</b> {v.get('fps_text') or '—'}")

        codec_lbl = v.get("codec_label") or "—"
        prof = v.get("profile")
        prof_str = f" ({prof})" if prof and prof != "—" else ""
        self.lbl_codec.setText(f"<b>Kodek:</b> {codec_lbl}{prof_str}")

        pix = v.get("pix_fmt") or "—"
        depth = v.get("bit_depth_text") or ""
        depth_str = f" ({depth})" if depth and depth != "—" else ""
        self.lbl_pixfmt.setText(f"<b>Format:</b> {pix}{depth_str}")

        self.lbl_bitrate.setText(f"<b>Bitrate:</b> {v.get('bitrate_text') or '—'}")

        c_sum = c.get("summary") or "—"
        c_rng = c.get("range")
        rng_str = f" [{c_rng}]" if c_rng and c_rng != "—" else ""
        self.lbl_color.setText(f"<b>Kolor:</b> {c_sum}{rng_str}")

        if a:
            a_lbl = a.get("codec_label") or "Audio"
            sr = a.get("sample_rate_text") or ""
            ch = a.get("channels_text") or ""
            a_desc = f"{a_lbl}, {sr}, {ch}".strip(", ")
            self.lbl_audio.setText(f"<b>Audio:</b> {a_desc}")
        else:
            self.lbl_audio.setText("<b>Audio:</b> <span style='color:#888;'>Brak</span>")

        gpmf_txt = "<span style='color:#137333; font-weight:bold;'>TAK</span>" if info.get("gpmf") else "<span style='color:#666;'>NIE</span>"
        self.lbl_gpmf.setText(f"<b>GPMF:</b> {gpmf_txt}")

        self.update_telemetry(paired_telemetry)

    def set_error(self, filename: str, error_msg: str = "") -> None:
        self.lbl_res.setText("<span style='color:#d93025; font-weight:bold;'>Błąd odczytu</span>")
        self.lbl_fps.setText("—")
        self.lbl_codec.setText("—")
        self.lbl_pixfmt.setText("—")
        self.lbl_bitrate.setText("—")
        self.lbl_color.setText("—")
        self.lbl_audio.setText("—")
        self.lbl_gpmf.setText("—")

    def update_telemetry(self, paired_telemetry: str) -> None:
        if paired_telemetry:
            self.lbl_telem.setText(
                f"<b>FIT / GPX:</b> <span style='color:#0969da; font-weight:bold;'>{paired_telemetry}</span>"
            )
        else:
            self.lbl_telem.setText(
                "<b>FIT / GPX:</b> <span style='color:#888;'>Brak (auto / manualny)</span>"
            )

    def set_qp_progress(self, pct: int) -> None:
        self._qp_active = True
        self.btn_card_qp.setText("Anuluj QP")
        self.lbl_qp_info.setVisible(True)
        self.lbl_qp_info.setText(f"<b>Analiza QP:</b> w toku... <b>{pct}%</b>")

    def set_qp_result(self, info: dict[str, Any]) -> None:
        self._qp_active = False
        self.btn_card_qp.setText("Analiza QP")
        self.lbl_qp_info.setVisible(True)
        if not info.get("ok"):
            err = info.get("error") or "Nie udało się odczytać QP."
            self.lbl_qp_info.setStyleSheet(
                "QLabel { background-color: #fdf2f2; border: 1px solid #f8b4b4; "
                "border-radius: 4px; padding: 4px 8px; font-size: 11px; color: #9b1c1c; }"
            )
            self.lbl_qp_info.setText(f"<b>Błąd QP:</b> {err}")
            return

        avg = f"{info['avg']:.2f}" if info.get("avg") is not None else "—"
        med = str(info["median"]) if info.get("median") is not None else "—"
        mn = str(info["minimum"]) if info.get("minimum") is not None else "—"
        mx = str(info["maximum"]) if info.get("maximum") is not None else "—"
        frames = info.get("frames", 0)
        elapsed = f"{info.get('elapsed_s', 0.0):.1f}s"
        self.lbl_qp_info.setStyleSheet(
            "QLabel { background-color: #f1f8ff; border: 1px solid #c8e1ff; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; color: #0366d6; }"
        )
        self.lbl_qp_info.setText(
            f"<b>Rozkład QP:</b> Średnia <b>{avg}</b> | Mediana <b>{med}</b> | Min <b>{mn}</b> | Max <b>{mx}</b> "
            f"<span style='color:#555;'>({frames} klatek, {elapsed})</span>"
        )

    def set_qp_error(self, err_msg: str) -> None:
        self._qp_active = False
        self.btn_card_qp.setText("Analiza QP")
        self.lbl_qp_info.setVisible(True)
        self.lbl_qp_info.setStyleSheet(
            "QLabel { background-color: #fdf2f2; border: 1px solid #f8b4b4; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; color: #9b1c1c; }"
        )
        self.lbl_qp_info.setText(f"<b>Błąd QP:</b> {err_msg}")

    def reset_qp(self) -> None:
        self._qp_active = False
        self.btn_card_qp.setText("Analiza QP")
        self.lbl_qp_info.setVisible(False)
        self.lbl_qp_info.setText("")


class LoadTab(QWidget):
    """Zakładka wyboru plików źródłowych z podziałem na sekcję ładowania i diagnostykę sprzętu."""

    # Wyniki asynchronicznej inspekcji plików (worker → GUI)
    sig_file_info_ready = Signal(dict, int)
    sig_file_info_error = Signal(str, int)
    sig_card_info_ready = Signal(int, dict, int)
    sig_card_info_error = Signal(int, str, int)

    # Wyniki asynchronicznej analizy QP
    sig_qp_progress = Signal(int, int)   # (percent, gen)
    sig_qp_done = Signal(dict, int)      # (info: dict, gen)
    sig_qp_error = Signal(str, int)      # (message, gen)

    # Wynik asynchronicznego wyszukiwania AutoFIT
    sig_autofit_matched = Signal(str, int)  # (fit_path, gen)
    sig_autofit_status = Signal(str, str, int, str)  # (field_status, row_status, gen, tooltip)

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._video_paths: list[str] = []
        self._files_metadata: list[dict[str, Any]] = []
        self._card_widgets: list[VideoFileCardWidget] = []
        self._gpx_path: str = ""
        self._fit_path: str = ""
        self._manual_fit_path: str = ""
        self._manual_gpx_path: str = ""
        self._auto_fit_path: str = ""
        self._auto_gpx_path: str = ""
        self._user_selected_telemetry: bool = False
        self._autofit_gen: int = 0
        self._inspection_gen: int = 0
        self._autofit_cancel_event: threading.Event | None = None
        self._autofit_thread: threading.Thread | None = None
        self._autofit_in_progress: bool = False
        self._autofit_done_event = threading.Event()
        self._preflight_done_for_paths: list[str] = []
        self._dynamic_integrations_config: dict[str, Any] = {}

        # Stan analizy QP
        self._qp_gen: int = 0
        self._qp_path: str = ""
        self._qp_card_idx: int = 0
        self._qp_cancel_event: threading.Event | None = None

        # Stan paska postępu wczytywania: target (backend) vs display (GUI)
        self._loading = False
        self._load_target = 0.0
        self._load_display = 0.0
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(30)
        self._load_timer.timeout.connect(self._load_tick)

        self._build_ui()
        self._connect_local_signals()

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setAlignment(Qt.AlignTop)
        vbox.setContentsMargins(20, 16, 20, 16)
        vbox.setSpacing(12)

        # ── Górny układ ekranu — podział poziomy (lewa ~2/3, prawa ~1/3) ──
        top_hsplit = QHBoxLayout()
        top_hsplit.setSpacing(16)

        # ── Lewa część (~2/3 szerokości) ──────────────────────────────────
        left_box = QVBoxLayout()
        left_box.setSpacing(10)

        # Sekcja Pliki źródłowe
        group_sources = QGroupBox("Pliki źródłowe")
        group_sources.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        form_sources = QFormLayout(group_sources)
        form_sources.setSpacing(10)

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

        self.setAcceptDrops(True)

        # MP4 bar
        self.btn_mp4 = QPushButton("Wybierz plik(i) MP4...")
        self.btn_mp4.setMinimumHeight(34)
        self.btn_mp4.setCursor(Qt.PointingHandCursor)
        self.btn_mp4.setStyleSheet(self._placeholder_style)
        self.btn_mp4.clicked.connect(self._select_mp4)
        self.btn_mp4.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_mp4.customContextMenuRequested.connect(self._on_mp4_context_menu)
        form_sources.addRow("MP4 (wymagane):", self.btn_mp4)

        # Telemetry bar (FIT / GPX)
        self.btn_telemetry = QPushButton("Wybierz FIT/GPX (opcjonalnie)...")
        self.btn_telemetry.setMinimumHeight(34)
        self.btn_telemetry.setCursor(Qt.PointingHandCursor)
        self.btn_telemetry.setStyleSheet(self._placeholder_style)
        self.btn_telemetry.clicked.connect(self._select_telemetry)
        form_sources.addRow("FIT / GPX:", self.btn_telemetry)
        self.lbl_remote_status = QLabel(
            "Automatyczne wyszukiwanie FIT/GPX rozpoczyna się po wybraniu filmu. Źródło: Ustawienia."
        )
        self.lbl_remote_status.setTextFormat(Qt.PlainText)
        self.lbl_remote_status.setWordWrap(True)
        form_sources.addRow("Telemetria:", self.lbl_remote_status)

        left_box.addWidget(group_sources)

        # Przyciski akcji (Wczytaj / Wyczyść)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_load = QPushButton("Wczytaj")
        self.btn_load.setMinimumHeight(44)
        self.btn_load.setMinimumWidth(150)
        self.btn_load.setStyleSheet(
            "QPushButton { background-color: #0078d4; color: white; "
            "font-size: 14px; font-weight: bold; border: none; "
            "border-radius: 4px; padding: 6px 20px; }"
            "QPushButton:hover { background-color: #1084d4; }"
            "QPushButton:disabled { background-color: #555; }"
        )
        self.btn_load.clicked.connect(self._on_load)
        btn_row.addWidget(self.btn_load)

        self.btn_clear = QPushButton("Wyczyść")
        self.btn_clear.setMinimumHeight(44)
        self.btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(self.btn_clear)

        left_box.addLayout(btn_row)

        # Pasek postępu wczytywania
        self.load_progress = QProgressBar()
        self.load_progress.setRange(0, 100)
        self.load_progress.setValue(0)
        self.load_progress.setVisible(False)
        self.load_progress.setMinimumHeight(10)
        self.load_progress.setStyleSheet(
            "QProgressBar { min-height: 10px; border: 1px solid #999; "
            "border-radius: 5px; background: #eee; text-align: center; }"
            "QProgressBar::chunk { background-color: #0078d4; "
            "border-radius: 5px; }"
        )
        left_box.addWidget(self.load_progress)

        self.lbl_load_status = QLabel("")
        self.lbl_load_status.setStyleSheet("color: #666; font-size: 12px;")
        self.lbl_load_status.setVisible(False)
        left_box.addWidget(self.lbl_load_status)

        # Akcelerator podglądu GPU
        accel_row = QHBoxLayout()
        accel_row.setContentsMargins(0, 2, 0, 2)
        accel_row.setSpacing(6)
        lbl_gpu = QLabel("Podgląd GPU:")
        lbl_gpu.setStyleSheet("color: #666; font-size: 12px; font-weight: bold;")
        lbl_gpu.setFixedWidth(84)
        accel_row.addWidget(lbl_gpu)

        self.cmb_preview_accel = QComboBox()
        self.cmb_preview_accel.setMinimumWidth(150)
        self.cmb_preview_accel.setStyleSheet(
            "QComboBox { background-color: #2a2a2a; color: #ddd; "
            "border: 1px solid #555; border-radius: 3px; padding: 2px 8px; font-size: 12px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background-color: #2a2a2a; color: #ddd; selection-background-color: #0078d4; }"
        )
        self.cmb_preview_accel.addItem("Auto", "auto")
        for code in get_available_vendors():
            self.cmb_preview_accel.addItem(vendor_label(code), code)
        self.cmb_preview_accel.setCurrentIndex(0)
        self.cmb_preview_accel.currentIndexChanged.connect(self._on_accel_changed)
        accel_row.addWidget(self.cmb_preview_accel)
        accel_row.addStretch()
        left_box.addLayout(accel_row)

        self.lbl_info = QLabel("Nie wczytano plików.")
        self.lbl_info.setStyleSheet("color: #888; font-size: 12px;")
        left_box.addWidget(self.lbl_info)

        top_hsplit.addLayout(left_box, stretch=2)

        # ── Prawa część (~1/3 szerokości) — Panel możliwości sprzętu ──────
        self.hw_info_widget = HardwareInfoWidget(self)
        top_hsplit.addWidget(self.hw_info_widget, stretch=1)

        vbox.addLayout(top_hsplit)

        # ── Dolna sekcja: Informacje o filmie (wieloplikowe karty) ───────────
        info_group = QGroupBox("Informacje o filmie")
        info_group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        info_vbox = QVBoxLayout(info_group)
        info_vbox.setContentsMargins(10, 10, 10, 10)
        info_vbox.setSpacing(8)

        # Informacyjny komunikat przy miksie rozdzielczości
        self.lbl_mixed_res_banner = QLabel(
            "ℹ Wczytano pliki o różnych rozdzielczościach źródłowych. "
            "Każdy plik zachowuje własne parametry wejściowe."
        )
        self.lbl_mixed_res_banner.setStyleSheet(
            "QLabel { background-color: #e8f0fe; color: #1967d2; border: 1px solid #aecbfa; "
            "border-radius: 4px; padding: 6px 12px; font-size: 12px; font-weight: bold; }"
        )
        self.lbl_mixed_res_banner.setVisible(False)
        info_vbox.addWidget(self.lbl_mixed_res_banner)

        # Obszar przewijania kart (domyślnie ~5 kart, powyżej pionowy scrollbar)
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.cards_scroll.setMinimumHeight(320)
        self.cards_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #dcdcdc; border-radius: 4px; background-color: #f8f9fa; }"
        )

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setAlignment(Qt.AlignTop)
        self.cards_layout.setSpacing(8)
        self.cards_layout.setContentsMargins(6, 6, 6, 6)

        self.lbl_no_files = QLabel("Wybierz plik(i) MP4, aby zobaczyć informacje o filmach.")
        self.lbl_no_files.setAlignment(Qt.AlignCenter)
        self.lbl_no_files.setStyleSheet("color: #777777; font-size: 13px; padding: 30px;")
        self.cards_layout.addWidget(self.lbl_no_files)

        self.cards_scroll.setWidget(self.cards_container)
        info_vbox.addWidget(self.cards_scroll)

        # Widgety kompatybilności wstecznej (dla testów jednostkowych i analizy QP)
        self.lbl_file_info = QLabel("Wybierz plik MP4, aby zobaczyć informacje o filmie.")
        self.lbl_file_info.setVisible(False)
        info_vbox.addWidget(self.lbl_file_info)

        self.btn_analyze_qp = QPushButton("Analiza QP")
        self.btn_analyze_qp.setVisible(False)
        self.btn_analyze_qp.setEnabled(False)
        self.btn_analyze_qp.clicked.connect(self._on_analyze_qp)
        info_vbox.addWidget(self.btn_analyze_qp)

        self.lbl_qp_result = QLabel(QP_PLACEHOLDER)
        self.lbl_qp_result.setVisible(False)
        info_vbox.addWidget(self.lbl_qp_result)

        vbox.addWidget(info_group, stretch=1)

    # ═════════════════════════════════════════════════════════════════════
    # Wybór plików i obsługa kart
    # ═════════════════════════════════════════════════════════════════════

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(u.toLocalFile().lower().endswith((".mp4", ".mov", ".m4v")) for u in urls):
                event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        if event.mimeData().hasUrls():
            video_files = [
                u.toLocalFile() for u in event.mimeData().urls()
                if u.toLocalFile().lower().endswith((".mp4", ".mov", ".m4v"))
            ]
            if video_files:
                event.acceptProposedAction()
                self.set_video_paths(video_files, start_search=True)

    def keyPressEvent(self, event: Any) -> None:
        from PySide6.QtGui import QKeySequence, QGuiApplication
        if event.matches(QKeySequence.Paste):
            cb_text = QGuiApplication.clipboard().text()
            if cb_text:
                self.set_video_paths(cb_text, start_search=True)
                return
        super().keyPressEvent(event)

    def _on_mp4_context_menu(self, pos: Any) -> None:
        from PySide6.QtWidgets import QMenu, QInputDialog
        from PySide6.QtGui import QGuiApplication
        menu = QMenu(self)
        act_browse = menu.addAction("Przeglądaj pliki...")
        act_paste = menu.addAction("Wklej ścieżkę ze schowka (Ctrl+V)")
        act_input = menu.addAction("Wprowadź ścieżkę ręcznie...")
        action = menu.exec(self.btn_mp4.mapToGlobal(pos))
        if action == act_browse:
            self._select_mp4()
        elif action == act_paste:
            cb_text = QGuiApplication.clipboard().text()
            if cb_text:
                self.set_video_paths(cb_text, start_search=True)
        elif action == act_input:
            text, ok = QInputDialog.getText(self, "Wprowadź ścieżkę", "Ścieżka do pliku MP4:")
            if ok and text.strip():
                self.set_video_paths(text.strip(), start_search=True)

    def set_video_paths(self, paths: list[str] | str, start_search: bool = True) -> None:
        """Ustawia ścieżki plików MP4 i natychmiast rozpoczyna automatyczne wyszukiwanie telemetrii."""
        if isinstance(paths, str):
            raw_items = [p.strip().strip('"').strip("'") for p in paths.replace("\n", ";").split(";")]
            paths = [p for p in raw_items if p]

        valid_paths = [str(Path(p).resolve()) for p in paths if Path(p).is_file()]
        if not valid_paths:
            return

        self._video_paths = valid_paths
        self.btn_mp4.setText("; ".join(valid_paths))
        self.btn_mp4.setStyleSheet(self._selected_style)
        self.btn_mp4.setToolTip("; ".join(valid_paths))
        self._rebuild_cards(valid_paths)
        self._start_multi_info_inspection()

        if not self._user_selected_telemetry:
            self._autofit_gen += 1
            if start_search:
                self._start_auto_telemetry_preflight(valid_paths, gen=self._autofit_gen)

    def _select_mp4(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Wybierz plik(i) MP4", "",
            "Wideo (*.mp4 *.MP4 *.mov *.MOV)",
        )
        if paths:
            self.set_video_paths(paths, start_search=True)

    def _select_telemetry(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik FIT lub GPX", "",
            "Pliki telemetryczne (*.fit *.FIT *.gpx *.GPX);;FIT (*.fit *.FIT);;GPX (*.gpx *.GPX)",
        )
        if path:
            if self._autofit_cancel_event is not None:
                self._autofit_cancel_event.set()
            self._autofit_in_progress = False
            self._autofit_done_event.set()
            self.lbl_remote_status.setText("Wybrany ręcznie FIT/GPX ma pierwszeństwo przed automatem.")
            self.lbl_remote_status.setToolTip(path)
            self._user_selected_telemetry = True
            ext = path.lower()
            if ext.endswith(".fit"):
                self._manual_fit_path = path
                self._manual_gpx_path = ""
                self._fit_path = path
                self._gpx_path = ""
            elif ext.endswith(".gpx"):
                self._manual_gpx_path = path
                self._manual_fit_path = ""
                self._gpx_path = path
                self._fit_path = ""
            self.btn_telemetry.setText(Path(path).name)
            self.btn_telemetry.setToolTip(path)
            self.btn_telemetry.setStyleSheet(self._selected_style)
            self._update_telemetry_on_all_cards()

    def _get_current_telemetry_name(self) -> str:
        if self._fit_path:
            return Path(self._fit_path).name
        if self._gpx_path:
            return Path(self._gpx_path).name
        return ""

    def _update_telemetry_on_all_cards(self) -> None:
        telem_name = self._get_current_telemetry_name()
        for card in self._card_widgets:
            card.update_telemetry(telem_name)

    def _rebuild_cards(self, paths: list[str]) -> None:
        self._clear_cards()
        if not paths:
            self.lbl_no_files.setVisible(True)
            return

        self.lbl_no_files.setVisible(False)
        self._files_metadata = [{} for _ in paths]
        telem_name = self._get_current_telemetry_name()
        for idx, p in enumerate(paths):
            card = VideoFileCardWidget(idx, p, self.cards_container)
            card.update_telemetry(telem_name)
            card.sig_qp_clicked.connect(self._on_card_qp_clicked)
            self.cards_layout.addWidget(card)
            self._card_widgets.append(card)

    def _clear_cards(self) -> None:
        for card in self._card_widgets:
            card.deleteLater()
        self._card_widgets.clear()
        self._files_metadata.clear()
        self.lbl_no_files.setVisible(True)

    def _update_mixed_resolutions_banner(self) -> None:
        resolutions: set[tuple[int, int]] = set()
        for meta in self._files_metadata:
            if meta and isinstance(meta, dict):
                v = meta.get("video") or {}
                w = v.get("width")
                h = v.get("height")
                if w and h:
                    resolutions.add((int(w), int(h)))
        if len(resolutions) > 1:
            self.lbl_mixed_res_banner.setVisible(True)
        else:
            self.lbl_mixed_res_banner.setVisible(False)

    def get_files_metadata(self) -> list[dict[str, Any]]:
        """Zwraca listę metadanych dla wszystkich wczytanych plików."""
        return list(self._files_metadata)

    def get_file_metadata(self, index: int) -> dict[str, Any] | None:
        """Zwraca metadane dla konkretnego pliku po indeksie."""
        if 0 <= index < len(self._files_metadata):
            return self._files_metadata[index]
        return None

    # ═════════════════════════════════════════════════════════════════════
    # Auto Telemetry Preflight (Local FIT/GPX + Remote Provider)
    # ═════════════════════════════════════════════════════════════════════

    def _get_integrations_config(self) -> dict[str, Any]:
        """Pobiera aktualną konfigurację integracji (dynamiczną + dyskową)."""
        cfg = {}
        try:
            from src.runtime_paths import get_app_root
            p = get_app_root() / "def_layout.json"
            if p.exists():
                import json
                cfg = json.loads(p.read_text(encoding="utf-8")).get("integrations", {})
        except Exception:
            pass
            
        if not cfg:
            try:
                from pathlib import Path
                import json
                def_file = Path("def_layout.json")
                if def_file.exists():
                    cfg = json.loads(def_file.read_text(encoding="utf-8")).get("integrations", {})
            except Exception:
                pass
                
        # Nadpisz dynamicznymi zmianami z UI (np. zmienione źródło bez restartu)
        cfg.update(self._dynamic_integrations_config)
        return cfg

    def _try_auto_fit_search(self, paths: list[str], gen: int | None = None) -> None:
        """Kompatybilność z istniejącym API testów — uruchamia preflight telemetrii."""
        self._start_auto_telemetry_preflight(paths, gen=gen)

    def _start_auto_telemetry_preflight(self, paths: list[str], gen: int | None = None) -> None:
        """Asynchroniczne wyszukiwanie telemetrii: najpierw lokalny katalog MP4, potem remote provider."""
        if not paths or self._user_selected_telemetry:
            return

        if self._autofit_cancel_event is not None:
            self._autofit_cancel_event.set()

        self._autofit_cancel_event = threading.Event()
        cancel_ev = self._autofit_cancel_event

        if gen is None:
            self._autofit_gen += 1
            gen = self._autofit_gen
        request_gen = gen

        self._autofit_in_progress = True
        self._autofit_done_event.clear()
        self._preflight_done_for_paths = []

        # Wyczyść poprzednio automatycznie przypisaną telemetrię
        self._auto_fit_path = ""
        self._auto_gpx_path = ""
        self._fit_path = ""
        self._gpx_path = ""

        self.btn_telemetry.setText("Wyszukiwanie lokalnych plik?w FIT/GPX...")
        self.btn_telemetry.setToolTip("")
        self.btn_telemetry.setStyleSheet(self._placeholder_style)
        self.lbl_remote_status.setText("Wyszukiwanie lokalnych plik?w FIT/GPX...")
        self.lbl_remote_status.setToolTip("")
        self._update_telemetry_on_all_cards()

        cfg = self._get_integrations_config()

        def status_cb(field_st: str, row_st: str, tooltip: Optional[str] = None) -> None:
            if not cancel_ev.is_set() and request_gen == self._autofit_gen and not self._user_selected_telemetry:
                self.sig_autofit_status.emit(field_st, row_st, request_gen, str(tooltip or ""))

        def worker() -> None:
            try:
                from src.integrations.auto_telemetry_preflight import run_auto_telemetry_preflight
                res_path = run_auto_telemetry_preflight(
                    video_paths=paths,
                    config=cfg,
                    on_status=status_cb,
                    cancel_event=cancel_ev,
                )
                if res_path is not None and not cancel_ev.is_set() and request_gen == self._autofit_gen and not self._user_selected_telemetry:
                    self.sig_autofit_matched.emit(str(res_path), request_gen)
            except Exception as e:
                print(f"[AutoPreflight] Error running telemetry preflight: {e}", flush=True)
            finally:
                if request_gen == self._autofit_gen:
                    self._autofit_in_progress = False
                    self._autofit_done_event.set()
                    self._preflight_done_for_paths = [str(Path(p).resolve()) for p in paths]

        thread = threading.Thread(target=worker, name="TeleM-AutoTelemetry", daemon=True)
        self._autofit_thread = thread
        thread.start()

    def _on_autofit_status(self, field_st: str, row_st: str, gen: int, tooltip: str) -> None:
        """Aktualizacja statusu w polu FIT/GPX oraz wierszu Telemetria w wątku GUI."""
        if gen != self._autofit_gen or self._user_selected_telemetry:
            return
        if field_st:
            self.btn_telemetry.setText(field_st)
            self.btn_telemetry.setToolTip(tooltip)
            if field_st.endswith("✓"):
                self.btn_telemetry.setStyleSheet(self._selected_style)
            else:
                self.btn_telemetry.setStyleSheet(self._placeholder_style)
        if row_st:
            self.lbl_remote_status.setText(row_st)
            self.lbl_remote_status.setToolTip(tooltip)

    def _on_autofit_matched(self, telem_path: str, gen: int) -> None:
        """Obsłuż dopasowany plik FIT/GPX z asynchronicznego preflightu (wątek główny GUI)."""
        if gen != self._autofit_gen or self._user_selected_telemetry:
            return
        p = Path(telem_path)
        ext = p.suffix.lower()
        if ext == ".fit":
            self._auto_fit_path = telem_path
            self._auto_gpx_path = ""
            self._fit_path = telem_path
            self._gpx_path = ""
        elif ext == ".gpx":
            self._auto_gpx_path = telem_path
            self._auto_fit_path = ""
            self._gpx_path = telem_path
            self._fit_path = ""

        btn_txt = self.btn_telemetry.text()
        if not btn_txt.endswith("✓"):
            btn_txt = f"{p.name} ✓"
        self.btn_telemetry.setText(btn_txt)
        self.btn_telemetry.setToolTip(telem_path)
        self.btn_telemetry.setStyleSheet(self._selected_style)
        self._update_telemetry_on_all_cards()

    # ═════════════════════════════════════════════════════════════════════
    # Wczytywanie i obsługa paska postępu
    # ═════════════════════════════════════════════════════════════════════

    def _on_load(self) -> None:
        if not self._video_paths:
            QMessageBox.warning(self, "Brak pliku", "Wybierz plik MP4.")
            return

        # Jeśli preflight jeszcze trwa, poczekaj krótko na jego zakończenie
        if self._autofit_in_progress:
            deadline = time.time() + 4.0
            while self._autofit_in_progress and time.time() < deadline:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
                time.sleep(0.02)

        self._start_loading()
        if not self._fit_path and not self._gpx_path:
            self.lbl_remote_status.setText("Wczytywanie filmu i ustalanie czasu dla wyszukiwania telemetrii…")
        self.signals.sig_files_selected.emit(
            list(self._video_paths), self._gpx_path, self._fit_path,
        )

    def _start_loading(self) -> None:
        self._loading = True
        self._load_target = 0.0
        self._load_display = 0.0
        self.btn_load.setEnabled(False)
        self.load_progress.setVisible(True)
        self.load_progress.setValue(0)
        self.lbl_load_status.setVisible(True)
        self.lbl_load_status.setText("Wczytywanie...")
        self.lbl_info.setText("Wczytywanie...")
        self._load_timer.start()

    def _on_load_progress(self, percent: int, text: str) -> None:
        if not self._loading:
            return
        pct = float(max(0, min(100, percent)))
        if pct > self._load_target:
            self._load_target = pct
        if text:
            self.lbl_load_status.setText(text)
        if percent >= 100:
            self._finish_loading_success()

    def _finish_loading_success(self) -> None:
        if self.lbl_remote_status.text().startswith("Wczytywanie filmu i ustalanie czasu"):
            self.lbl_remote_status.setText(
                "Nie uzyskano wyniku automatycznego wyszukiwania. "
                "Sprawdź źródło w Ustawieniach lub wybierz FIT/GPX ręcznie."
            )
        self._loading = False
        self._load_target = 100.0
        self.lbl_load_status.setText("Gotowe")
        self.lbl_info.setText("Wczytano pomyślnie.")
        self.btn_load.setEnabled(True)

    def _on_load_error(self, msg: str) -> None:
        if not self._loading:
            return
        self._loading = False
        self._load_timer.stop()
        self.lbl_load_status.setText("Błąd")
        self.lbl_info.setText(f"Błąd wczytywania: {msg}")
        self.btn_load.setEnabled(True)

    def _load_tick(self) -> None:
        delta = self._load_target - self._load_display
        if delta <= 0.2:
            self._load_display = self._load_target
        else:
            self._load_display += max(delta * 0.2, 0.3)
            if self._load_display > self._load_target:
                self._load_display = self._load_target
        self.load_progress.setValue(int(round(self._load_display)))
        if self._load_display >= 100.0:
            self.load_progress.setValue(100)
            self._load_timer.stop()

    def _reset_loading_ui(self) -> None:
        self._loading = False
        self._load_timer.stop()
        self._load_target = 0.0
        self._load_display = 0.0
        self.load_progress.setVisible(False)
        self.lbl_load_status.setVisible(False)
        self.btn_load.setEnabled(True)

    def _on_accel_changed(self, _index: int) -> None:
        vendor = self.cmb_preview_accel.currentData()
        self.signals.sig_preview_accel_changed.emit(vendor or "auto")

    def _on_clear(self) -> None:
        if self._autofit_cancel_event is not None:
            self._autofit_cancel_event.set()
            self._autofit_cancel_event = None
        self._autofit_in_progress = False
        self._autofit_done_event.set()
        self._autofit_gen += 1
        self._inspection_gen += 1

        self.lbl_remote_status.setText("Automatyczne wyszukiwanie FIT/GPX rozpoczyna się po wybraniu filmu. Źródło: Ustawienia.")
        self.lbl_remote_status.setToolTip("")
        self.btn_mp4.setText("Wybierz plik(i) MP4...")
        self.btn_mp4.setStyleSheet(self._placeholder_style)
        self.btn_mp4.setToolTip("")
        self.btn_telemetry.setText("Wybierz FIT/GPX (opcjonalnie)...")
        self.btn_telemetry.setStyleSheet(self._placeholder_style)
        self.btn_telemetry.setToolTip("")
        self._video_paths = []
        self._gpx_path = ""
        self._fit_path = ""
        self._manual_fit_path = ""
        self._manual_gpx_path = ""
        self._auto_fit_path = ""
        self._auto_gpx_path = ""
        self._user_selected_telemetry = False
        self._preflight_done_for_paths = []
        self._files_metadata = []
        self.lbl_info.setText("Nie wczytano plików.")
        self.lbl_file_info.setText("Wybierz plik MP4, aby zobaczyć informacje o filmie.")
        self.lbl_mixed_res_banner.setVisible(False)
        self._clear_cards()
        self._reset_qp_state()
        self.btn_analyze_qp.setEnabled(False)
        self._reset_loading_ui()

    # ═════════════════════════════════════════════════════════════════════
    # Asynchroniczna inspekcja plików
    # ═════════════════════════════════════════════════════════════════════

    def _connect_local_signals(self) -> None:
        self.signals.sig_remote_telemetry_status.connect(self._on_remote_telemetry_status)
        self.signals.sig_settings_changed.connect(self._on_settings_changed)
        self.sig_autofit_status.connect(self._on_autofit_status)
        self.sig_file_info_ready.connect(self._on_file_info_ready)
        self.sig_file_info_error.connect(self._on_file_info_error)
        self.sig_card_info_ready.connect(self._on_card_info_ready)
        self.sig_card_info_error.connect(self._on_card_info_error)
        self.sig_qp_progress.connect(self._on_qp_progress)
        self.sig_qp_done.connect(self._on_qp_done)
        self.sig_qp_error.connect(self._on_qp_error)
        self.sig_autofit_matched.connect(self._on_autofit_matched)
        self.signals.sig_progress.connect(self._on_load_progress)
        self.signals.sig_error.connect(self._on_load_error)

    def _on_settings_changed(self, name: str, value: Any) -> None:
        self._dynamic_integrations_config[name] = value
        if name == "auto_activity_source":
            if self._video_paths and not self._user_selected_telemetry:
                self._autofit_gen += 1
                self._start_auto_telemetry_preflight(self._video_paths, gen=self._autofit_gen)

    def _on_remote_telemetry_status(self, payload: dict) -> None:
        # A worker for an older video must never replace the current video's status.
        normalize = lambda paths: [os.path.normcase(os.path.abspath(str(p))) for p in paths]
        if normalize(payload.get("video_paths", [])) != normalize(self._video_paths):
            return
        if self._user_selected_telemetry:
            return
        self.lbl_remote_status.setText(payload.get("message", ""))
        self.lbl_remote_status.setToolTip(str(payload.get("path") or ""))

    def _start_info_inspection(self) -> None:
        """Kompatybilność z istniejącym API — inspekcja wczytanych plików MP4."""
        self._start_multi_info_inspection()

    def _start_multi_info_inspection(self) -> None:
        if not self._video_paths:
            return

        if len(self._card_widgets) != len(self._video_paths):
            self._rebuild_cards(self._video_paths)

        self._inspection_gen += 1
        gen = self._inspection_gen
        self.lbl_file_info.setText("Odczytywanie informacji o filmie...")
        self.btn_analyze_qp.setEnabled(True)
        self._reset_qp_state()

        paths_snapshot = list(self._video_paths)

        def worker() -> None:
            ffprobe = resolve_ffprobe()
            for idx, p in enumerate(paths_snapshot):
                if gen != self._inspection_gen:
                    return
                try:
                    info = inspect_mp4(p, ffprobe)
                    if gen != self._inspection_gen:
                        return
                    self.sig_card_info_ready.emit(idx, info, gen)
                    if idx == 0:
                        self.sig_file_info_ready.emit(info, gen)
                except Exception:
                    if gen != self._inspection_gen:
                        return
                    name = str(Path(p).name)
                    self.sig_card_info_error.emit(idx, name, gen)
                    if idx == 0:
                        self.sig_file_info_error.emit(name, gen)

        threading.Thread(target=worker, daemon=True).start()

    def _on_file_info_ready(self, info: dict, gen: int) -> None:
        if gen != self._inspection_gen:
            return
        self.lbl_file_info.setText(format_file_info_text(info))

    def _on_file_info_error(self, _name: str, gen: int) -> None:
        if gen != self._inspection_gen:
            return
        self.lbl_file_info.setText("Nie udało się odczytać informacji o filmie.")

    def _on_card_info_ready(self, idx: int, info: dict, gen: int) -> None:
        if gen != self._inspection_gen:
            return
        if 0 <= idx < len(self._files_metadata):
            self._files_metadata[idx] = info
        if 0 <= idx < len(self._card_widgets):
            paired = self._get_current_telemetry_name()
            self._card_widgets[idx].update_info(info, paired)
        self._update_mixed_resolutions_banner()

    def _on_card_info_error(self, idx: int, name: str, gen: int) -> None:
        if gen != self._inspection_gen:
            return
        if 0 <= idx < len(self._card_widgets):
            self._card_widgets[idx].set_error(name, "Nie udało się odczytać informacji o filmie.")

    # ═════════════════════════════════════════════════════════════════════
    # Analiza QP
    # ═════════════════════════════════════════════════════════════════════

    def _on_card_qp_clicked(self, video_path: str, card_idx: int) -> None:
        if self._qp_cancel_event is not None and self._qp_card_idx == card_idx:
            self._qp_cancel_event.set()
            return
        if not Path(video_path).exists():
            if 0 <= card_idx < len(self._card_widgets):
                self._card_widgets[card_idx].set_qp_error("Plik nie istnieje.")
            return
        self.analyze_qp(video_path, card_idx=card_idx)

    def _on_analyze_qp(self) -> None:
        if not self._video_paths:
            return
        path = self._video_paths[0]
        if self._qp_cancel_event is not None:
            self._qp_cancel_event.set()
            return
        if not Path(path).exists():
            self._show_qp_error("Plik nie istnieje.")
            if self._card_widgets:
                self._card_widgets[0].set_qp_error("Plik nie istnieje.")
            return
        self.analyze_qp(path, card_idx=0)

    def analyze_qp(self, video_path: str, card_idx: int = 0) -> None:
        """Uruchom rzeczywistą analizę QP poza wątkiem GUI."""
        self._qp_gen += 1
        gen = self._qp_gen
        self._qp_path = video_path
        self._qp_card_idx = card_idx
        self._qp_cancel_event = threading.Event()
        self.btn_analyze_qp.setText("Anuluj analizę QP")
        self.lbl_qp_result.setText(QP_PLACEHOLDER + "\n\nAnaliza QP: 0%")
        if 0 <= card_idx < len(self._card_widgets):
            self._card_widgets[card_idx].set_qp_progress(0)

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
        if 0 <= self._qp_card_idx < len(self._card_widgets):
            self._card_widgets[self._qp_card_idx].set_qp_progress(pct)

    def _on_qp_done(self, info: dict, gen: int) -> None:
        if gen != self._qp_gen:
            return
        self._qp_cancel_event = None
        self.btn_analyze_qp.setText("Analiza QP")
        if 0 <= self._qp_card_idx < len(self._card_widgets):
            self._card_widgets[self._qp_card_idx].set_qp_result(info)
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
        if 0 <= self._qp_card_idx < len(self._card_widgets):
            self._card_widgets[self._qp_card_idx].set_qp_error(msg)
        self._show_qp_error(msg)

    def _show_qp_error(self, msg: str) -> None:
        self.lbl_qp_result.setText(
            QP_PLACEHOLDER + "\n\nNie udało się odczytać QP dla tego strumienia.\n" + msg
        )

    def _reset_qp_state(self) -> None:
        self._qp_gen += 1
        if self._qp_cancel_event is not None:
            self._qp_cancel_event.set()
        self._qp_cancel_event = None
        self._qp_path = ""
        self._qp_card_idx = 0
        self.btn_analyze_qp.setText("Analiza QP")
        self.lbl_qp_result.setText(QP_PLACEHOLDER)
        for card in self._card_widgets:
            card.reset_qp()
