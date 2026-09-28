"""Zakładka Rendering — podgląd HUD (bez filmu) + opcje eksportu + realny progress.

Układ:
- LEWO: HUD Preview (podgląd samej nakładki, czarne tło, bez filmu); gdy
  zakładka nie renderuje, w tym miejscu widoczny jest współdzielony podgląd
  wideo; zakres eksportu ustawia osobny pasek IN/OUT poniżej.
- PRAWO: Ustawienia eksportu + przycisk [ EKSPORTUJ ] + Anuluj.
- DÓŁ: rzeczywisty pasek postępu + statystyki (Frame/%/FPS/Elapsed/ETA/Status).

Progress bazuje na RZECZYWISTYCH ukończonych klatkach pipeline'u (kontrakt
on_render_progress: completed/total), NIE na timerze ani czasie źródła.
HUD Preview aktualizowany maksymalnie 1×/s (latest-state, bez GPU readback,
bez backpressure) — renderowany w wątku GUI, poza pętlą eksportera.
"""

from __future__ import annotations

import os
import gc
import json
import re
import subprocess
import threading
import time
import traceback
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QComboBox,
    QLineEdit, QPushButton, QProgressBar, QLabel, QFileDialog, QMessageBox,
    QScrollArea, QFrame, QSizePolicy, QCheckBox, QListWidget, QListWidgetItem,
)
from PIL import Image

from src.gui.qt.signals import get_signals
from src.gui.qt.widgets.video_preview import VideoPreview, preview_aspect_size
from src.gui.qt.widgets.discrete_slider import DiscreteSlider, BitrateControl
from src.gui.export_preview import compose_export_preview
from src.ffmpeg.encoder_profile import EncoderProfile, DEFAULT_ENCODER_PROFILE, LEGACY_DEFAULT_ENCODER_PROFILE
from src.ffmpeg.amd_hevc_preview import (
    AMDContinuousHEVCPreview,
    AMDGPUNativeFrameTapPreview,
)
from src.telemetry_resolver import build_activity_range_cache
from src.render_progress import (
    RenderCancelReason,
    RenderCancelRequest,
    RenderProgressState,
    format_render_progress_status,
    next_render_generation_id,
)
from src.gui.export_queue import ExportJob, ExportQueue


EXPORT_PREVIEW_DIM_ALPHA = 24


def dim_export_preview_qimage(
    frame: QImage,
    *,
    render_active: bool,
    alpha: int = EXPORT_PREVIEW_DIM_ALPHA,
) -> QImage:
    """Return an owned Export Preview copy, dimmed only during rendering."""
    result = frame.convertToFormat(QImage.Format_ARGB32).copy()
    if not render_active:
        return result
    painter = QPainter(result)
    painter.fillRect(result.rect(), QColor(0, 0, 0, int(alpha)))
    painter.end()
    return result


class RenderTab(QWidget):
    """Zakładka opcji renderowania z podglądem i zakresem eksportu IN/OUT."""

    # ── Zakresy JEDNEGO wspólnego paska postępu eksportu (0..100%) ───────
    # "Przygotowywanie HUD"  ->  0..10%
    # rendering klatek       -> 10..98%
    # finalizacja (mux)      -> 98..100%
    _HUD_PREP_START = 0.0
    _HUD_PREP_END = 10.0
    _RENDER_START = 10.0
    _RENDER_END = 98.0
    _FINALIZE_START = 98.0
    _FINALIZE_END = 100.0
    _EXPORT_PREVIEW_INTERVAL_S = 2.0

    def __init__(self, preview: VideoPreview | None = None) -> None:
        super().__init__()
        self.signals = get_signals()
        self._controller: object = None
        self._gpu_capabilities = None
        self._owns_preview = preview is None
        self.video_preview = preview if preview is not None else VideoPreview()
        # Zakres eksportu IN/OUT w oryginalnym czasie oraz całkowitych klatkach
        self._in_orig: float | None = None
        self._out_orig: float | None = None
        self._in_frame: int | None = None
        self._out_frame: int | None = None
        self._boundary_regions: list[tuple[float, float]] = []
        self._user_edited_output = False
        self._last_output_dir: str = ""
        self._source_dimensions: tuple[int | None, int | None] = (None, None)
        # Stan renderingu / HUD preview (latest-state, maks. 1 Hz)
        self._rendering = False
        self._cancelling = False
        self._render_start = 0.0
        self._render_total = 0
        self._hud_ts: float | None = None
        self._hud_chart_data = None
        self._hud_prepare_cache: dict | None = None
        self._last_preview_time = 0.0
        self._preview_busy = False
        self._preview_lock = threading.Lock()
        self._preview_pending_ts: float | None = None
        self._preview_request_seq = 0
        self._preview_emitted_seq = 0
        self._preview_worker_active = False
        self._preview_worker_thread: threading.Thread | None = None
        self._preview_stop_event = threading.Event()
        self._preview_generation_id = 0
        self._preview_decode_active = 0
        self._preview_failed = False
        self._preview_fault_injected = False
        self._preview_update_times_ms: list[float] = []
        self._preview_worker_starts = 0
        self._preview_resources_reported = False
        self._preview_decoder = "none"
        self._preview_hardware_decode = "off"
        self._preview_device = "CPU"
        self._export_preview_lightweight = False
        self._preview_encoder_text = "amd"
        self._preview_hud_option = "Auto"
        self._preview_cached_video_frame: Image.Image | None = None
        self._preview_last_video_decode_ts: float | None = None
        self._preview_had_lifecycle = False
        self._preview_snapshot_labels: set[str] = set()
        self._pending_hud_switch_log = False
        self._render_generation_id = 0
        self._render_state_enabled = False
        self._render_state: RenderProgressState | None = None
        self._export_preview_native = False
        self._export_preview_hevc = False
        self._amd_export_preview_session: AMDContinuousHEVCPreview | AMDGPUNativeFrameTapPreview | None = None
        self._export_preview_gpu_tap = False
        self._last_continuous_hevc_stats: dict[str, object] = {}
        self._gpu_tap_pending_payload: tuple | None = None
        self._gpu_tap_signal_pending = False
        self._export_preview_logged = False
        self._export_preview_log_lock = threading.Lock()
        # Płynna animacja wspólnego paska: target (backend) vs display (GUI)
        self._render_target = 0.0
        self._render_display = 0.0
        self._is_indeterminate = False
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(30)
        self._render_timer.timeout.connect(self._render_tick)
        # Stan i timer fazy finalizacji
        self._in_finalize = False
        self._finalize_start_mono: float | None = None
        self._finalize_stage: str = ""
        self._finalize_drain_pct: float | None = None
        self._finalize_file_size: int = 0
        self._finalize_write_speed: float = 0.0
        self._finalize_stall_warning: bool = False
        self._finalize_stall_seconds: int = 0
        self._last_finalize_tick_sec: int = -1
        self._build_ui()
        self._connect_signals()
        self.chk_hud_preview.stateChanged.connect(self._on_preview_checkbox_changed)
        if self._owns_preview:
            self._connect_preview_signals()
        self._log_preview_resource_snapshot("A_fresh_before_render")
        # ── Kolejka eksportu ──────────────────────────────────────────────
        self._export_queue = None   # inicjalizowany w _init_export_queue()
        self._queue_paused = True
        self._active_queue_job_id: str | None = None
        self._current_render_queue_job_id: str | None = None

    # ═════════════════════════════════════════════════════════════════════
    # Budowa UI
    # ═════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        # ── Poziom główny: LEWO podgląd / PRAWO opcje+eksport ────────────
        main = QHBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(8)

        # LEWY: HUD Preview (podczas renderingu) / wideo IN/OUT (idle)
        self.left_panel = QWidget()
        self.left_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 4, 4, 4)
        left_layout.setSpacing(4)

        # HUD Preview widget (czarne tło, bez filmu) — domyślnie ukryty
        self.hud_preview_label = QLabel("Renderowanie...")
        self.hud_preview_label.setAlignment(Qt.AlignCenter)
        self.hud_preview_label.setStyleSheet(
            "QLabel { background-color: #000000; color: #888; "
            "border: 1px solid #333; font-size: 15px; }"
        )
        self.hud_preview_label.setVisible(False)
        left_layout.addWidget(self.hud_preview_label, 0)

        # Współdzielony, neutralny podgląd wideo (tryb idle)
        self.preview_slot = QWidget()
        self.preview_slot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_slot_layout = QVBoxLayout(self.preview_slot)
        self.preview_slot_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_slot_layout.setSpacing(0)
        left_layout.addWidget(self.preview_slot, 0)
        if self._owns_preview:
            self.preview_slot_layout.addWidget(self.video_preview)

        left_layout.addLayout(self._build_inout_bar())
        left_layout.addStretch(1)

        main.addWidget(self.left_panel)

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

        self.cmb_render_mode = QComboBox()
        self.cmb_render_mode.addItem("GPU", "gpu")
        self.cmb_render_mode.addItem("GPU + CPU (eksperymentalny)", "hybrid")
        self.cmb_render_mode.addItem("CPU", "cpu")
        self.cmb_render_mode.setToolTip(
            "GPU: sprawdzona ścieżka produkcyjna. CPU: software renderer. "
            "GPU + CPU jest eksperymentalny; bez bezpiecznego wspólnego "
            "handoffu do jednego enkodera końcowego automatycznie pozostaje GPU-only."
        )
        self.cmb_render_mode.currentIndexChanged.connect(
            lambda idx: self.signals.sig_settings_changed.emit(
                "render_mode", self.cmb_render_mode.itemData(idx) or "gpu"
            )
        )
        form.addRow("Tryb renderowania:", self.cmb_render_mode)

        self.cmb_encoder = QComboBox()
        # auto = wykryty najlepszy backend, amd = AMD AMF, nv = NVIDIA NVENC,
        # intel = Intel QuickSync (INTEL_FORCE — bez cross-GPU fallback),
        # cpu = software
        self.cmb_encoder.addItems(["auto", "amd", "nv", "intel", "cpu"])
        self.cmb_encoder.setToolTip(
            "auto = wykryty najlepszy backend, amd = AMD AMF (GPU), "
            "cpu_x265 = CPU HEVC x265 (10-bit, GPU decode/compositor, brak limitu rozdzielczości AMF), "
            "nv = NVIDIA NVENC, intel = Intel QuickSync, cpu = software"
        )
        try:
            from src.ffmpeg_pipeline import detect_best_encoder
            best_enc = detect_best_encoder()
            idx = self.cmb_encoder.findText(best_enc)
            if idx >= 0:
                self.cmb_encoder.setCurrentIndex(idx)
        except Exception:
            pass
        form.addRow("Encoder:", self.cmb_encoder)

        self.widget_amd_options = QWidget()
        layout_amd = QFormLayout(self.widget_amd_options)
        layout_amd.setContentsMargins(0, 0, 0, 0)
        layout_amd.setSpacing(4)

        self.cmb_amd_decode = QComboBox()
        self.cmb_amd_decode.addItem("GPU — sprzętowe (zalecane)", "gpu")
        self.cmb_amd_decode.addItem("CPU — programowe", "cpu")
        self.cmb_amd_decode.setToolTip(
            "Wybór metody dekodowania materiału wideo w backendzie AMD.\n"
            "Tryb CPU może być znacznie wolniejszy od GPU i mocno obciążać procesor."
        )

        self.lbl_cpu_warning = QLabel("Tryb CPU może być znacznie wolniejszy od GPU i mocno obciążać procesor.")
        self.lbl_cpu_warning.setStyleSheet("color: #e6a700; font-size: 11px; font-weight: normal;")
        self.lbl_cpu_warning.setVisible(False)

        def _on_decode_changed(idx: int) -> None:
            val = self.cmb_amd_decode.itemData(idx)
            self.lbl_cpu_warning.setVisible(val == "cpu")
            self.signals.sig_settings_changed.emit("amd_decode_mode", val)

        self.cmb_amd_decode.currentIndexChanged.connect(_on_decode_changed)

        row_decode = QVBoxLayout()
        row_decode.setSpacing(4)
        row_decode.addWidget(self.cmb_amd_decode)
        row_decode.addWidget(self.lbl_cpu_warning)
        layout_amd.addRow("Dekodowanie AMD:", row_decode)

        self.cmb_amd_quality = DiscreteSlider([
            ("Fast", "FAST"),
            ("Balanced", "BALANCED"),
            ("Quality", "QUALITY"),
        ])
        self.cmb_amd_quality.setToolTip(
            "Wybór profilu jakości kodowania HEVC w backendzie AMD AMF.\n"
            "Fast = AMF SPEED (szybki, standardowy)\n"
            "Balanced = AMF BALANCED (zbalansowany)\n"
            "Quality = AMF QUALITY (maksymalna jakość kosztem szybkości)"
        )

        def _on_quality_changed(idx: int) -> None:
            val = self.cmb_amd_quality.itemData(idx) or "FAST"
            self.signals.sig_settings_changed.emit("amd_encoder_quality", val)

        self.cmb_amd_quality.currentIndexChanged.connect(_on_quality_changed)
        layout_amd.addRow("Preset jakości AMD:", self.cmb_amd_quality)
        form.addRow(self.widget_amd_options)

        # ── NVIDIA Options (Stage 8L) ──────────────────────────────────
        self.widget_nvidia_options = QWidget()
        layout_nvidia = QFormLayout(self.widget_nvidia_options)
        layout_nvidia.setContentsMargins(0, 0, 0, 0)
        layout_nvidia.setSpacing(6)

        self.cmb_nvidia_backend = QComboBox()
        self.cmb_nvidia_backend.addItem("NVIDIA CUDA", "legacy_cuda")
        self.cmb_nvidia_backend.addItem("NVIDIA Native D3D11 (Experimental)", "native_d3d11")
        self.cmb_nvidia_backend.setToolTip(
            "NVIDIA CUDA: hybrydowy pipeline z workerami CPU i FFmpeg NVENC (Domyślny/Produkcyjny).\n"
            "NVIDIA Native D3D11 (Experimental): akcelerowany sprzętowo pipeline D3D11VA + Direct2D HUD + GPU map + NVENC."
        )

        from src.ffmpeg.nvidia_config import is_nvidia_native_available
        nv_native_ok, nv_native_reason = is_nvidia_native_available()
        idx_native = self.cmb_nvidia_backend.findData("native_d3d11")
        if not nv_native_ok and idx_native >= 0:
            self.cmb_nvidia_backend.setItemText(idx_native, f"NVIDIA Native D3D11 (Experimental / niedostępny: {nv_native_reason})")
        idx_legacy = self.cmb_nvidia_backend.findData("legacy_cuda")
        if idx_legacy >= 0:
            self.cmb_nvidia_backend.setCurrentIndex(idx_legacy)

        layout_nvidia.addRow("Backend NVIDIA:", self.cmb_nvidia_backend)

        self.cmb_nvidia_codec = QComboBox()
        self.cmb_nvidia_codec.addItems(["HEVC", "AV1", "H.264 (SDR)"])
        layout_nvidia.addRow("Kodek NVIDIA:", self.cmb_nvidia_codec)

        self.cmb_nvidia_quality = QComboBox()
        self.cmb_nvidia_quality.addItems(["Fast", "Quality", "Max Quality"])
        layout_nvidia.addRow("Jakość:", self.cmb_nvidia_quality)

        self.chk_compression_analysis = QCheckBox("Analiza kompresji podczas eksportu")
        self.chk_compression_analysis.setChecked(True)
        self.chk_compression_analysis.setToolTip("Pomiary QP/Quantizer w czasie rzeczywistym podczas renderowania NVENC")
        layout_nvidia.addRow(self.chk_compression_analysis)

        def _update_nvidia_quality_options():
            codec = self.cmb_nvidia_codec.currentText().strip().upper()
            curr_qual = self.cmb_nvidia_quality.currentText()
            self.cmb_nvidia_quality.blockSignals(True)
            self.cmb_nvidia_quality.clear()
            self.cmb_nvidia_quality.addItems(["Fast", "Quality", "Max Quality"])
            if curr_qual in ["Fast", "Quality", "Max Quality"]:
                self.cmb_nvidia_quality.setCurrentText(curr_qual)
            else:
                self.cmb_nvidia_quality.setCurrentText("Quality")
            self.cmb_nvidia_quality.blockSignals(False)

        # ── CPU Options (libx265) ──────────────────────────────────
        self.widget_cpu_options = QWidget()
        layout_cpu = QFormLayout(self.widget_cpu_options)
        layout_cpu.setContentsMargins(0, 0, 0, 0)
        layout_cpu.setSpacing(4)

        self.cmb_x265_preset = DiscreteSlider([
            "ultrafast", "superfast", "veryfast", "faster", "fast", "medium"
        ])
        self.cmb_x265_preset.setCurrentText("fast")
        self.cmb_x265_preset.setToolTip(
            "Preset kodowania CPU libx265 (10-bit). 'fast' to rekomendowany domyślny preset dla 4K i 8K."
        )
        layout_cpu.addRow("Preset x265:", self.cmb_x265_preset)

# ── Intel Options (Etap 8B) ──────────────────────────────────
        self.widget_intel_options = QWidget()
        layout_intel = QFormLayout(self.widget_intel_options)
        layout_intel.setContentsMargins(0, 0, 0, 0)
        layout_intel.setSpacing(6)

        self.cmb_intel_codec = QComboBox()
        self.cmb_intel_codec.addItem("AV1 — 10-bit HDR (Zalecany)", "av1")
        self.cmb_intel_codec.addItem("H.264 — 8-bit SDR", "h264")
        self.cmb_intel_codec.addItem("H.265 — 10-bit HDR", "hevc")

        try:
            from src.ffmpeg.intel_native_exporter import query_intel_capabilities
            intel_caps = query_intel_capabilities()
        except Exception:
            intel_caps = {"AV1_AVAILABLE": True, "H264_AVAILABLE": True, "HEVC_AVAILABLE": True}

        idx_hevc = self.cmb_intel_codec.findData("hevc")
        if not intel_caps.get("HEVC_AVAILABLE", False) and idx_hevc >= 0:
            model = self.cmb_intel_codec.model()
            if model is not None:
                item = model.item(idx_hevc) if hasattr(model, "item") else None
                if item is not None:
                    item.setEnabled(False)
                    item.setText("H.265 (Niedostępny na aktualnym sterowniku/runtime Intel)")
                    item.setToolTip("Niedostępny na aktualnym sterowniku/runtime Intel")

        self.cmb_intel_codec.setToolTip(
            "Wybór sprzętowego enkodera Intel Quick Sync Video (oneVPL).\n"
            "AV1: 10-bit HDR (HLG BT.2020, produkcyjny default).\n"
            "H.264: 8-bit SDR (BT.709 tone-mapped z zachowaniem świateł).\n"
            "H.265: 10-bit HDR (HLG BT.2020)."
        )

        self.lbl_intel_codec_info = QLabel("Format: HDR 10-bit (HLG / BT.2020)")
        self.lbl_intel_codec_info.setStyleSheet("color: #72b0ff; font-size: 11px; font-weight: normal;")

        def _on_intel_codec_changed(_idx: int) -> None:
            c = self.cmb_intel_codec.currentData()
            if c == "h264":
                self.lbl_intel_codec_info.setText("Format: SDR 8-bit (BT.709 tone-mapped)")
                self.lbl_intel_codec_info.setStyleSheet("color: #aaffaa; font-size: 11px; font-weight: normal;")
            elif c == "hevc":
                if intel_caps.get("HEVC_AVAILABLE", False):
                    self.lbl_intel_codec_info.setText("Format: HDR 10-bit (HLG / BT.2020)")
                    self.lbl_intel_codec_info.setStyleSheet("color: #72b0ff; font-size: 11px; font-weight: normal;")
                else:
                    self.lbl_intel_codec_info.setText("Niedostępny na aktualnym sterowniku/runtime Intel")
                    self.lbl_intel_codec_info.setStyleSheet("color: #ff7777; font-size: 11px; font-weight: normal;")
            else:
                self.lbl_intel_codec_info.setText("Format: HDR 10-bit (HLG / BT.2020)")
                self.lbl_intel_codec_info.setStyleSheet("color: #72b0ff; font-size: 11px; font-weight: normal;")

        self.cmb_intel_codec.currentIndexChanged.connect(_on_intel_codec_changed)

        row_intel_codec = QVBoxLayout()
        row_intel_codec.setSpacing(2)
        row_intel_codec.addWidget(self.cmb_intel_codec)
        row_intel_codec.addWidget(self.lbl_intel_codec_info)
        layout_intel.addRow("Koder wideo:", row_intel_codec)

        # Intel Encoder Profile
        from src.ffmpeg.encoder_profile import EncoderProfile, DEFAULT_ENCODER_PROFILE, LEGACY_DEFAULT_ENCODER_PROFILE
        self.cmb_intel_profile = DiscreteSlider([
            ("Szybki", "fast"),
            ("Zbalansowany", "balanced"),
            ("Jakość", "quality"),
        ])
        idx_bal = self.cmb_intel_profile.findData(DEFAULT_ENCODER_PROFILE.value)
        if idx_bal >= 0:
            self.cmb_intel_profile.setCurrentIndex(idx_bal)
        self.cmb_intel_profile.setToolTip(
            "Profil jakości/szybkości enkodera Intel Quick Sync (oneVPL):\n"
            "Szybki: maksymalna wydajność kodowania.\n"
            "Zbalansowany: domyślny profil produkcyjny.\n"
            "Jakość: wyższa złożoność i jakość kodowania."
        )
        layout_intel.addRow("Profil enkodera:", self.cmb_intel_profile)
        self.cmb_encoder_profile = self.cmb_intel_profile
        form.addRow(self.widget_intel_options)
        def _update_backend_visibility():
            enc = self.cmb_encoder.currentText().strip().lower()
            if enc == "auto":
                try:
                    from src.ffmpeg_pipeline import detect_best_encoder
                    enc = detect_best_encoder().lower()
                except Exception:
                    enc = ""
            is_amd = enc in ("amd", "amd_native")
            is_nv = enc in ("nv", "nvidia")
            is_intel = enc in ("intel", "qsv")
            is_cpu = enc in ("cpu", "cpu_x265")
            self.widget_amd_options.setVisible(is_amd)
            self.widget_nvidia_options.setVisible(is_nv)
            self.widget_intel_options.setVisible(is_intel)
            if hasattr(self, "widget_cpu_options"):
                self.widget_cpu_options.setVisible(is_cpu)
            if is_nv:
                self.cmb_nvidia_codec.setEnabled(True)
                self.cmb_nvidia_quality.setEnabled(True)
                self.chk_compression_analysis.setEnabled(True)

            # Dynamic AMF Hardware Capability Detection (no blanket vendor disable)
            if hasattr(self, "cmb_resolution"):
                try:
                    from src.ffmpeg.amd_capabilities import get_gpu_capabilities
                    caps = self._gpu_capabilities or get_gpu_capabilities()
                    max_w = caps.max_encode_width if caps.status == "OK" else None
                    max_h = caps.max_encode_height if caps.status == "OK" else None
                except Exception:
                    caps = None
                    max_w, max_h = None, None

                from src.ffmpeg.command_builder import RESOLUTION_MAP
                for i in range(self.cmb_resolution.count()):
                    res_name = self.cmb_resolution.itemText(i)
                    target_res = RESOLUTION_MAP.get(res_name)
                    if target_res is None and res_name.strip().lower() == "source":
                        sw, sh = self._source_dimensions
                        if sw and sh:
                            target_res = (sw, sh)
                    if target_res is not None and is_amd:
                        w, h = target_res
                        supported = caps.supports_encode(w, h) if caps is not None else None
                        if supported is False:
                            tip = (
                                f"Sprzętowy enkoder tego GPU obsługuje maksymalnie "
                                f"{max_w}×{max_h}."
                            )
                            self.cmb_resolution.setItemEnabled(i, False, tip)
                        elif supported is None:
                            self.cmb_resolution.setItemEnabled(
                                i, True,
                                "Capabilities GPU UNKNOWN — rozdzielczość zostanie sprawdzona przed renderem.",
                            )
                        else:
                            self.cmb_resolution.setItemEnabled(i, True)
                    else:
                        # CPU x265, NVIDIA, Intel have no AMF limit
                        self.cmb_resolution.setItemEnabled(i, True)

                if is_amd:
                    curr_idx = self.cmb_resolution.currentIndex()
                    if not self.cmb_resolution.isItemEnabled(curr_idx):
                        old_resolution = self.cmb_resolution.currentText()
                        self.cmb_resolution.setCurrentText("4k")
                        if old_resolution != "4k":
                            source_w, source_h = self._source_dimensions
                            requested = (
                                f"{source_w}x{source_h}"
                                if source_w and source_h
                                else old_resolution
                            )
                            print(
                                "OUTPUT_RESOLUTION_CLAMPED=True "
                                f"FROM={requested} TO=3840x2160 "
                                "REASON=ENCODER_CAPABILITY",
                                flush=True,
                            )

        self._update_backend_visibility = _update_backend_visibility
        self.cmb_encoder.currentIndexChanged.connect(lambda _: self._update_backend_visibility())
        self.cmb_nvidia_backend.currentIndexChanged.connect(lambda _: _update_backend_visibility())

        form.addRow(self.widget_nvidia_options)
        form.addRow(self.widget_cpu_options)

        self.cmb_resolution = DiscreteSlider([
            "480p", "720p", "1080p", "4k", "5.3k", "8k", "source",
        ])
        self.cmb_resolution.setCurrentText("source")
        form.addRow("Rozdzielczość:", self.cmb_resolution)
        _update_backend_visibility()

        self.cmb_rotation = QComboBox()
        self.cmb_rotation.addItems(["auto", "0", "90", "180", "270"])
        form.addRow("Rotacja:", self.cmb_rotation)

        self.cmb_update_rate = DiscreteSlider(["Quarter", "Half", "Full"])
        self.cmb_update_rate.setCurrentText("Full")
        form.addRow("Częstotliwość HUD:", self.cmb_update_rate)

        self.cmb_hud_resolution = DiscreteSlider(["Auto", "100%", "75%", "50%"])
        self.cmb_hud_resolution.setCurrentText("Auto")
        self.cmb_hud_resolution.setToolTip(
            "Rozmiar rastra HUD względem rozdzielczości eksportu; "
            "Auto wybiera zwalidowany 75% dla Intel 4K (2560x1440), "
            "dla pozostałych 100%."
        )
        form.addRow("Rozdzielczość HUD:", self.cmb_hud_resolution)

        self.edit_bitrate = BitrateControl(min_mbps=5, max_mbps=120, default_mbps=40)
        form.addRow("Bitrate:", self.edit_bitrate)

        row_out = QHBoxLayout()
        self.edit_output = QLineEdit("output_h265.mp4")
        self.edit_output.setMinimumHeight(28)
        self.edit_output.textEdited.connect(self._on_output_text_edited)
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

        # ── KOLEJKA EKSPORTU ─────────────────────────────────────────────
        right_layout.addWidget(self._build_queue_panel())

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

        main.addWidget(self.right_panel, 1)

        vbox.addLayout(main, 1)

        # ── Dół: pasek postępu + statystyki ──────────────────────────────
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(4, 0, 4, 4)
        bottom_layout.setSpacing(2)

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
        bottom_layout.addWidget(self.progress)

        # Statystyki: tworzone RAZ, jedna linia, czarny tekst, stała
        # wysokość (bez re-layoutu / migania podczas aktualizacji).
        self.lbl_stats = QLabel("Gotowy")
        self.lbl_stats.setStyleSheet("QLabel { color: black; font-size: 12px; }")
        self.lbl_stats.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_stats.setWordWrap(False)
        bottom_layout.addWidget(self.lbl_stats)
        self.lbl_compression_stats = QLabel("")
        self.lbl_compression_stats.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; font-weight: bold; }")
        self.lbl_compression_stats.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_compression_stats.setWordWrap(False)
        self.lbl_compression_stats.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_compression_stats.setVisible(False)
        bottom_layout.addWidget(self.lbl_compression_stats)

        vbox.addWidget(bottom_widget)

    # ═════════════════════════════════════════════════════════════════════
    # KOLEJKA EKSPORTU
    # ═════════════════════════════════════════════════════════════════════

    def _build_queue_panel(self) -> QGroupBox:
        """Zbuduj panel kolejki eksportu z listą jobów i opcjami YouTube."""
        group = QGroupBox("Kolejka eksportu")
        group.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: bold; margin-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        vbox = QVBoxLayout(group)
        vbox.setContentsMargins(6, 14, 6, 6)
        vbox.setSpacing(4)

        # ── Lista jobów ──────────────────────────────────────────────────
        self.queue_list = QListWidget()
        self.queue_list.setMaximumHeight(180)
        self.queue_list.setMinimumHeight(60)
        self.queue_list.setAlternatingRowColors(True)
        self.queue_list.setStyleSheet(
            "QListWidget { font-size: 11px; }"
            "QListWidget::item:selected { background: #2a6099; color: white; }"
        )
        self.queue_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.queue_list.setToolTip("Lista zaplanowanych zadań renderowania")
        self.queue_list.itemClicked.connect(self._on_queue_item_clicked)
        self.queue_list.itemDoubleClicked.connect(self._on_queue_item_double_clicked)
        vbox.addWidget(self.queue_list)
        
        from PySide6.QtGui import QShortcut, QKeySequence
        from PySide6.QtCore import Qt
        shortcut_del = QShortcut(QKeySequence("Delete"), self.queue_list)
        shortcut_del.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut_del.activated.connect(self._on_queue_remove)

        # ── Opcje YouTube per-job ────────────────────────────────────────
        yt_frame = QFrame()
        yt_frame.setFrameShape(QFrame.Shape.StyledPanel)
        yt_frame.setStyleSheet("QFrame { background: #f5f5f5; border-radius: 4px; }")
        yt_layout = QFormLayout(yt_frame)
        yt_layout.setContentsMargins(6, 4, 6, 4)
        yt_layout.setSpacing(4)

        self.chk_yt_enabled = QCheckBox("Upload YouTube po renderze")
        self.chk_yt_enabled.setChecked(False)
        self.chk_yt_enabled.setToolTip(
            "Wymaga: pip install google-api-python-client google-auth-oauthlib\n"
            "Credentiale: %APPDATA%\\BikeRideHUD\\youtube_client_secret.json"
        )
        yt_layout.addRow(self.chk_yt_enabled)

        self.edit_yt_title = QLineEdit()
        self.edit_yt_title.setPlaceholderText("(domyślnie: nazwa pliku)")
        self.edit_yt_title.setEnabled(False)
        yt_layout.addRow("Tytuł YT:", self.edit_yt_title)

        self.cmb_yt_privacy = QComboBox()
        self.cmb_yt_privacy.addItem("Prywatny (private)", "private")
        self.cmb_yt_privacy.addItem("Niewidoczny (unlisted)", "unlisted")
        self.cmb_yt_privacy.addItem("Publiczny (public)", "public")
        self.cmb_yt_privacy.setEnabled(False)
        yt_layout.addRow("Prywatność:", self.cmb_yt_privacy)

        self.edit_yt_desc = QLineEdit()
        self.edit_yt_desc.setPlaceholderText("(opcjonalny opis)")
        self.edit_yt_desc.setEnabled(False)
        yt_layout.addRow("Opis:", self.edit_yt_desc)

        def _toggle_yt(state: int) -> None:
            on = self.chk_yt_enabled.isChecked()
            self.edit_yt_title.setEnabled(on)
            self.cmb_yt_privacy.setEnabled(on)
            self.edit_yt_desc.setEnabled(on)

        self.chk_yt_enabled.stateChanged.connect(_toggle_yt)
        vbox.addWidget(yt_frame)

        # ── Przyciski kontrolne ──────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.btn_queue_add = QPushButton("+ Dodaj")
        self.btn_queue_add.setMinimumHeight(26)
        self.btn_queue_add.setToolTip(
            "Dodaj bieżące ustawienia eksportu jako nowe zadanie w kolejce.\n"
            "Zadanie jest zamrożonym snapshotem — późniejsze zmiany go nie dotyczą."
        )
        self.btn_queue_add.clicked.connect(self._on_add_to_queue)
        btn_row.addWidget(self.btn_queue_add)

        self.btn_queue_remove = QPushButton("Usuń")
        self.btn_queue_remove.setMinimumHeight(26)
        self.btn_queue_remove.setToolTip("Usuń zaznaczony job (nie działa gdy trwa rendering)")
        self.btn_queue_remove.clicked.connect(self._on_queue_remove)
        btn_row.addWidget(self.btn_queue_remove)

        self.btn_queue_import = QPushButton("Import")
        self.btn_queue_import.setMinimumHeight(26)
        self.btn_queue_import.setToolTip("Importuj kolejkę z pliku *.telemqueue.json")
        self.btn_queue_import.clicked.connect(self._on_queue_import)
        btn_row.addWidget(self.btn_queue_import)

        self.btn_queue_export = QPushButton("Eksport")
        self.btn_queue_export.setMinimumHeight(26)
        self.btn_queue_export.setToolTip("Eksportuj kolejkę do pliku *.telemqueue.json")
        self.btn_queue_export.clicked.connect(self._on_queue_export)
        btn_row.addWidget(self.btn_queue_export)

        btn_row.addStretch()

        self.btn_queue_start = QPushButton("▶ Start")
        self.btn_queue_start.setMinimumHeight(26)
        self.btn_queue_start.setToolTip("Uruchom / wznów przetwarzanie kolejki")
        self.btn_queue_start.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; padding: 2px 10px; }"
            "QPushButton:hover { background-color: #388e3c; }"
            "QPushButton:disabled { background-color: #aaa; }"
        )
        self.btn_queue_start.clicked.connect(self._on_queue_start)
        btn_row.addWidget(self.btn_queue_start)

        self.btn_queue_pause = QPushButton("⏸ Pauza")
        self.btn_queue_pause.setMinimumHeight(26)
        self.btn_queue_pause.setToolTip("Wstrzymaj kolejkę (aktywny render dobiegnie końca)")
        self.btn_queue_pause.setEnabled(False)
        self.btn_queue_pause.clicked.connect(self._on_queue_pause)
        btn_row.addWidget(self.btn_queue_pause)

        self.btn_queue_stop = QPushButton("⏹ STOP")
        self.btn_queue_stop.setMinimumHeight(26)
        self.btn_queue_stop.setToolTip("Zatrzymaj kolejkę i natychmiast anuluj bieżący render")
        self.btn_queue_stop.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; padding: 2px 10px; }"
            "QPushButton:hover { background-color: #d32f2f; }"
            "QPushButton:disabled { background-color: #aaa; }"
        )
        self.btn_queue_stop.clicked.connect(self._on_queue_stop)
        btn_row.addWidget(self.btn_queue_stop)

        vbox.addLayout(btn_row)

        # Status kolejki
        self.lbl_queue_status = QLabel("Kolejka: pusta")
        self.lbl_queue_status.setStyleSheet("QLabel { color: #666; font-size: 11px; }")
        vbox.addWidget(self.lbl_queue_status)

        return group

    def _init_export_queue(self) -> None:
        """Inicjuj ExportQueue (lazy — wywołaj po set_controller)."""
        if self._export_queue is not None:
            return
        try:
            self._export_queue = ExportQueue(signals=self.signals)
            self._export_queue.set_render_callback(self._queue_render_callback)
            self._export_queue.set_on_job_updated(self._queue_job_updated_from_thread)
            # Podłącz sygnały Qt (queued connection — thread-safe GUI update & dispatch)
            self.signals.sig_queue_job_updated.connect(self._on_queue_job_updated)
            self.signals.sig_queue_dispatch_render.connect(self._dispatch_queue_job_render)
            self.signals.sig_queue_started.connect(
                lambda: self._set_queue_btn_state(running=True)
            )
            self.signals.sig_queue_paused.connect(
                lambda: self._set_queue_btn_state(running=False)
            )
            self._refresh_queue_ui()
            print("[ExportQueue] Initialized", flush=True)
        except Exception as exc:
            print(f"[ExportQueue] Init error: {exc}", flush=True)

    def _queue_render_callback(self, job: ExportJob) -> None:
        """Wywołany przez ExportQueue gdy ma uruchomić render jobu (z wątku kolejki)."""
        # Emisja przez sygnał Qt zapewnia bezpieczny, cross-thread dispatch do pętli zdarzeń GUI
        self.signals.sig_queue_dispatch_render.emit(job)

    def _dispatch_queue_job_render(self, job: ExportJob) -> None:
        """GUI-thread: uruchom render dla jobu z kolejki."""
        from pathlib import Path
        from src.gui.export_queue import log_queue_trace, validate_job_snapshot

        # Section 4: Snapshot validation
        is_valid, error_reason = validate_job_snapshot(job)
        print(
            f"[QUEUE SNAPSHOT VALIDATION]\n"
            f"input_videos={job.video_paths}\n"
            f"fit_path={job.fit_path}\n"
            f"gpmf/json paths={[str(Path(p).with_suffix('.json')) for p in job.video_paths]}\n"
            f"layout snapshot keys={list((job.layout or {}).keys())}\n"
            f"output_path={job.output_path}\n"
            f"render_mode={job.options.get('render_mode', 'gpu')}\n"
            f"encoder={job.options.get('encoder', 'amd')}\n"
            f"hardware_decode={job.options.get('amd_decode_mode', 'gpu')}\n"
            f"quality={job.options.get('amd_encoder_quality', 'FAST')}\n"
            f"resolution={job.options.get('resolution', 'source')}\n"
            f"rotation={job.options.get('rotation', 'auto')}\n"
            f"hud_frequency={job.options.get('update_rate', '1')}\n"
            f"hud_resolution={job.options.get('hud_resolution_scale', 'Auto')}\n"
            f"bitrate={job.options.get('bitrate', '40M')}\n"
            f"preview={job.options.get('_gui_hud_preview_checkbox', False)}",
            flush=True,
        )

        if not is_valid:
            log_queue_trace(
                "QUEUE SNAPSHOT RESOLVE",
                job_id=job.job_id,
                output_path=job.output_path,
                input_videos=job.video_paths,
                extra=f"VALIDATION_FAILED: {error_reason}",
            )
            job.render_status = "error"
            job.render_error = error_reason
            if self._export_queue:
                self._export_queue.notify_render_done(
                    job.job_id, success=False, error_message=error_reason
                )
            return

        log_queue_trace(
            "QUEUE SNAPSHOT RESOLVE",
            job_id=job.job_id,
            output_path=job.output_path,
            input_videos=job.video_paths,
            extra="VALIDATION_PASS",
        )

        # Snapshot resolution onto controller
        self._restore_job_snapshot_onto_controller(job)

        import copy
        options = copy.deepcopy(job.options)
        options["output"] = job.output_path
        options["video_paths"] = list(job.video_paths)
        options["fit_path"] = job.fit_path
        options["gpx_path"] = job.gpx_path
        options["layout"] = copy.deepcopy(job.layout)

        # Canonical entrypoint
        success = self._start_render(options, job=job)
        if not success:
            log_queue_trace(
                "QUEUE DISPATCH FAILED",
                job_id=job.job_id,
                output_path=job.output_path,
                input_videos=job.video_paths,
                extra="controller/tab was busy",
            )
            if self._export_queue:
                self._export_queue.notify_render_done(
                    job.job_id, success=False, error_message="Render start rejected (busy)"
                )

    def _restore_job_snapshot_onto_controller(self, job: ExportJob) -> None:
        """Przywróć stan layoutu i wideo na kontrolerze z zamrożonego snapshotu."""
        ctrl = self._controller
        if ctrl is None:
            return
        curr_paths = [str(p) for p in getattr(ctrl, "video_paths", [])]
        job_paths = [str(p) for p in job.video_paths]
        paths_changed = (curr_paths != job_paths or getattr(ctrl, "video_path", None) is None)
        if paths_changed:
            ctrl.video_paths = [Path(p) for p in job.video_paths]
            ctrl.video_path = ctrl.video_paths[0] if ctrl.video_paths else None
            if hasattr(ctrl, "telemetry") and ctrl.telemetry is not None:
                ctrl.telemetry.start_dt_utc = None
                ctrl.telemetry._coverage_start = None
                if hasattr(ctrl.telemetry, "records"):
                    ctrl.telemetry.records = []
        if job.layout:
            import copy
            ctrl.layout = copy.deepcopy(job.layout)
        if job.fit_path:
            ctrl.fit_path = Path(job.fit_path)
        if job.gpx_path:
            ctrl.gpx_path = Path(job.gpx_path)
        ctrl._cut_regions = []

        # Check if telemetry is loaded on controller
        has_telem = False
        if hasattr(ctrl, "telemetry") and ctrl.telemetry is not None:
            if getattr(ctrl.telemetry, "speed_samples", None) or getattr(ctrl.telemetry, "gps_track", None):
                has_telem = True

        if paths_changed or not has_telem:
            if hasattr(ctrl, "_load_or_generate_telemetry"):
                try:
                    ctrl._load_or_generate_telemetry()
                except Exception as exc:
                    print(f"[RenderTab] Telemetry load for job failed: {exc}", flush=True)

            if paths_changed:
                try:
                    from src.multifile import build_timeline_from_paths
                    from src.video_helpers import find_executable
                    ffmpeg_exe = find_executable(
                        "ffmpeg",
                        [str(ctrl.base_dir / "ffmpeg.exe"), "ffmpeg.exe"] if hasattr(ctrl, "base_dir") else []
                    )
                    ffprobe_exe = find_executable(
                        "ffprobe",
                        [str(ctrl.base_dir / "ffprobe.exe"), "ffprobe.exe"] if hasattr(ctrl, "base_dir") else []
                    )
                    timeline = build_timeline_from_paths(
                        ctrl.video_paths,
                        ffmpeg_exe=ffmpeg_exe,
                        ffprobe_exe=ffprobe_exe,
                        base_dt=getattr(ctrl.telemetry, "start_dt_utc", None) if hasattr(ctrl, "telemetry") else None,
                        default_fps=getattr(ctrl, "fps", 30.0),
                    )
                    ctrl.video_timeline = timeline
                    ctrl.video_clips = list(timeline.clips)
                    ctrl.video_duration_s = timeline.project_duration_s
                    if timeline.clips and timeline.clips[0].absolute_start_dt is not None:
                        proj_start = timeline.clips[0].absolute_start_dt
                        if hasattr(ctrl, "telemetry") and ctrl.telemetry is not None:
                            ctrl.telemetry.start_dt_utc = proj_start
                            ctrl.telemetry._coverage_start = proj_start
                    from src.gui.export_queue import log_queue_trace
                    log_queue_trace(
                        "QUEUE TIMELINE REBUILT",
                        job_id=job.job_id,
                        output_path=job.output_path,
                        input_videos=job.video_paths,
                        extra=f"timeline_duration={timeline.project_duration_s}s",
                    )
                except Exception as e:
                    print(f"[RenderTab] Failed to rebuild timeline: {e}", flush=True)
        if job.fit_path and hasattr(ctrl, "telemetry") and ctrl.telemetry is not None:
            try:
                curr_fit = getattr(ctrl.telemetry, "fit_path", None)
                has_fit_track = bool(getattr(ctrl.telemetry, "fit_gps_track", None))
                if str(curr_fit) != str(job.fit_path) or not has_fit_track:
                    ctrl.telemetry.load_fit(
                        ctrl.video_path, getattr(ctrl.telemetry, "start_dt_utc", None),
                        manual_path=Path(job.fit_path),
                    )
            except Exception as exc:
                print(f"[RenderTab] FIT load for job failed: {exc}", flush=True)
        if hasattr(ctrl, "_ensure_map_context"):
            try:
                ctrl._ensure_map_context()
            except Exception:
                pass
        if hasattr(ctrl, "_trigger_map_background_prefetch"):
            try:
                ctrl._trigger_map_background_prefetch(reason="queue_job_restore")
            except Exception:
                pass
            if job.gpx_path and hasattr(ctrl, "telemetry") and ctrl.telemetry is not None:
                try:
                    ctrl.telemetry.load_gpx(
                        ctrl.video_path, getattr(ctrl.telemetry, "start_dt_utc", None),
                        manual_path=Path(job.gpx_path),
                    )
                except Exception as exc:
                    print(f"[RenderTab] GPX load for job failed: {exc}", flush=True)

    def _start_render(self, options: dict, job: ExportJob | None = None) -> bool:
        """CANONICAL RENDER ENTRYPOINT — wspólna ścieżka uruchamiania dla kolejki i EKSPORTUJ."""
        from src.gui.export_queue import log_queue_trace
        if self._rendering or self._cancelling:
            print(
                f"[RenderTab] _start_render: busy "
                f"rendering={self._rendering} cancelling={self._cancelling}",
                flush=True,
            )
            return False

        if not self.chk_hud_preview.isChecked() and self._preview_had_lifecycle:
            self._log_preview_resource_snapshot("E_before_next_render_preview_off")
            self._preview_had_lifecycle = False

        self.lbl_compression_stats.setText("")
        self.lbl_compression_stats.setVisible(False)

        from src.render_progress import next_render_generation_id
        self._render_generation_id = next_render_generation_id()
        options["_render_generation_id"] = self._render_generation_id
        self._last_export_fps = None
        self._last_export_qp = None

        if job is not None:
            self._active_queue_job_id = job.job_id
            self._current_render_queue_job_id = job.job_id
            options["_queue_job_id"] = job.job_id
            options["_export_queue"] = self._export_queue
            options["output"] = job.output_path
        else:
            self._active_queue_job_id = None
            self._current_render_queue_job_id = None
            self._ensure_range_applied()

        self._rendering = True
        self._cancelling = False
        self._render_state_enabled = True
        self._render_start = time.monotonic()
        self._render_total = 0
        self._hud_ts = None
        self._hud_chart_data = None
        self._hud_prepare_cache = None
        self._stop_export_preview("queue_render" if job else "new_render")
        self._start_export_preview_generation()
        self._export_preview_logged = False
        self._preview_encoder_text = options.get("encoder", self.cmb_encoder.currentText())
        self._preview_hud_option = options.get("hud_resolution_scale", self.cmb_hud_resolution.currentText())
        self.btn_render.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._is_indeterminate = False
        self._render_target = 0.0
        self._render_display = 0.0
        self._render_timer.start()
        prep_msg = "Przygotowanie renderingu (kolejka)..." if job else "Przygotowanie renderingu..."
        self._set_stats(0, 0, 0.0, 0.0, prep_msg, item_label="Prep")
        self.signals.sig_render_state.emit(
            RenderProgressState(
                generation_id=self._render_generation_id,
                state="preparing",
                prep_label=prep_msg,
                elapsed_s=0.0,
            )
        )

        hud_on = bool(options.get("_gui_hud_preview_checkbox", self.chk_hud_preview.isChecked()))
        selected_encoder = str(options.get("encoder", "")).strip().lower()
        resolved_amd = selected_encoder == "amd"
        if selected_encoder == "auto":
            try:
                from src.ffmpeg import detect_best_encoder
                resolved_amd = detect_best_encoder() == "amd"
            except Exception:
                resolved_amd = False
        is_nv_selected = selected_encoder in ("nv", "nvidia")
        is_nv_native = bool(
            is_nv_selected
            and options.get("nvidia_backend") in ("native_d3d11", "NVIDIA Native D3D11")
        )
        self._export_preview_hevc = bool(hud_on and resolved_amd)
        self._export_preview_gpu_tap = bool(hud_on and (resolved_amd or is_nv_native))
        self._export_preview_lightweight = False
        self._export_preview_native = bool(
            hud_on and self._uses_native_export_video()
            and not self._export_preview_hevc
            and not is_nv_native
        )
        if self._export_preview_hevc:
            preview_width = max(2, int(os.environ.get("AMD_EXPORT_PREVIEW_WIDTH", "960")))
            preview_height = max(2, int(round(preview_width * 9 / 16)))
            self._amd_export_preview_session = AMDGPUNativeFrameTapPreview(
                width=preview_width,
                height=preview_height,
                target_fps=float(os.environ.get("AMD_EXPORT_PREVIEW_FPS", "2")),
                on_frame=self._on_amd_gpu_preview_frame,
                on_error=self._on_amd_gpu_preview_error,
            )
            self._amd_export_preview_session.start()
            self._preview_decoder = "native D3D11 GPU frame tap"
            self._preview_hardware_decode = "D3D11 VideoProcessor + async staging"
            self._preview_device = "AMD native D3D11"
        elif hud_on and is_nv_native:
            self._preview_decoder = "native D3D11 GPU frame tap"
            self._preview_hardware_decode = "D3D11 VideoProcessor + async staging"
            self._preview_device = "NVIDIA native D3D11"
            options["_nvidia_preview_tap"] = lambda buf, w, h, s, f, pts: self._on_amd_gpu_preview_frame(buf, w, h)
        elif self._export_preview_native:
            self._preview_decoder = "MPV/QMedia"
            self._preview_hardware_decode = "existing preview setting"
            self._preview_device = "preview player"

        if self._export_preview_native:
            self.preview_slot.setVisible(True)
            self.hud_preview_label.setVisible(False)
            hud = getattr(self.video_preview, "hud_overlay", None)
            if hud is not None:
                hud.set_hud_pixmap(None)
                hud.sync_geometry()
                hud.show()
                hud.raise_()
        else:
            self.preview_slot.setVisible(not hud_on)
            self.hud_preview_label.setVisible(hud_on)
            self.hud_preview_label.setText(
                "Uruchamianie podglądu HEVC..." if self._export_preview_hevc else "Renderowanie..."
            )
        options["_amd_export_preview_session"] = (
            self._amd_export_preview_session if self._export_preview_hevc else None
        )
        options["_amd_export_preview_config"] = (
            {
                "enabled": True,
                "width": getattr(self._amd_export_preview_session, "width", 960),
                "height": getattr(self._amd_export_preview_session, "height", 540),
                "target_fps": getattr(self._amd_export_preview_session, "target_fps", 2.0),
            }
            if self._export_preview_hevc else None
        )
        preview_w = getattr(self._amd_export_preview_session, "width", 0) if self._export_preview_hevc else (960 if (hud_on and is_nv_native) else 0)
        preview_h = getattr(self._amd_export_preview_session, "height", 0) if self._export_preview_hevc else (540 if (hud_on and is_nv_native) else 0)
        preview_fps = float(os.environ.get("AMD_EXPORT_PREVIEW_FPS", "2")) if self._export_preview_hevc else (8.0 if (hud_on and is_nv_native) else 0.0)
        print(
            f"[EXPORT PREVIEW] enabled={'True' if (self._export_preview_hevc or (hud_on and is_nv_native)) else 'False'} "
            f"backend={'gpu_frame_tap' if (self._export_preview_hevc or (hud_on and is_nv_native)) else 'disabled'} "
            f"target_fps={preview_fps:g} target_size={preview_w}x{preview_h}",
            flush=True,
        )

        log_queue_trace(
            "QUEUE DISPATCH",
            job_id=getattr(job, "job_id", ""),
            output_path=options.get("output", ""),
            input_videos=getattr(job, "video_paths", []),
            extra=f"encoder={selected_encoder} render_mode={options.get('render_mode')}",
        )
        self.signals.sig_render_requested.emit(options)
        return True

    def _start_render_from_options(self, options: dict, job: ExportJob | None = None) -> bool:
        """Alias dla _start_render (wsteczna kompatybilność)."""
        return self._start_render(options, job=job)


    def _queue_job_updated_from_thread(self, job: ExportJob) -> None:
        """Wywoływany z wątku kolejki — emituj sygnał Qt (thread-safe marshalowanie)."""
        try:
            self.signals.sig_queue_job_updated.emit(job)
        except Exception:
            pass

    def _on_queue_job_updated(self, job: ExportJob) -> None:
        """GUI thread — odśwież wiersz jobu w liście kolejki."""
        self._refresh_queue_ui()

    def _toggle_job_expansion(self, job_id: str) -> None:
        """Przełącz stan zwinięcia/rozwinięcia szczegółów ukończonego joba."""
        if not self._export_queue:
            return
        job = self._export_queue.get_job(job_id)
        if job and job.render_status == "done":
            job.is_expanded = not getattr(job, "is_expanded", False)
            self._refresh_queue_ui()

    def _on_queue_item_clicked(self, item: QListWidgetItem) -> None:
        job_id = item.data(Qt.UserRole)
        if not job_id or not self._export_queue:
            return
        from PySide6.QtWidgets import QApplication
        modifiers = QApplication.keyboardModifiers()
        if modifiers & (Qt.ShiftModifier | Qt.ControlModifier):
            return
        self._toggle_job_expansion(job_id)

    def _on_queue_item_double_clicked(self, item: QListWidgetItem) -> None:
        job_id = item.data(Qt.UserRole)
        if not job_id or not self._export_queue:
            return
        self._toggle_job_expansion(job_id)

    def _refresh_queue_ui(self) -> None:
        """Pełne odświeżenie listy jobów w kolejce (GUI thread)."""
        q = self._export_queue
        if q is None:
            self.lbl_queue_status.setText("Kolejka: niezainicjowana")
            return
        jobs = q.get_jobs()
        selected_ids = {
            item.data(Qt.UserRole)
            for item in self.queue_list.selectedItems()
            if item.data(Qt.UserRole)
        }
        self.queue_list.clear()
        for job in jobs:
            text = self._queue_job_text(job)
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, job.job_id)
            # Kolor wiersza wg statusu
            from PySide6.QtGui import QColor as _QColor
            if job.render_status == "running":
                item.setForeground(_QColor("#2e7d32"))
            elif job.render_status in ("done",) and job.upload_status in ("idle", "done"):
                item.setForeground(_QColor("#888"))
            elif job.render_status == "error" or job.upload_status == "error":
                item.setForeground(_QColor("#c62828"))
            self.queue_list.addItem(item)
            if job.job_id in selected_ids:
                item.setSelected(True)

        total = len(jobs)
        queued = sum(1 for j in jobs if j.render_status == "queued")
        running = sum(1 for j in jobs if j.render_status == "running")
        done = sum(1 for j in jobs if j.is_done())
        parts = []
        if total == 0:
            parts.append("pusta")
        else:
            parts.append(f"{total} zadań")
        if running:
            parts.append(f"{running} renderowanie")
        if queued:
            parts.append(f"{queued} oczekuje")
        if done:
            parts.append(f"{done} ukończone")
        self.lbl_queue_status.setText("Kolejka: " + ", ".join(parts))

    def _queue_job_text(self, job: ExportJob) -> str:
        """Sformatuj wiersz opisu jobu dla QListWidget."""
        name = job.display_name()
        r = job.render_status
        up = job.upload_status
        pct_r = f"{job.render_progress * 100:.0f}%" if r in ("running", "finalizing") else ""
        pct_u = f"{job.upload_progress * 100:.0f}%" if up == "running" else ""

        status_map = {
            "queued": "OCZEKUJE",
            "preparing": "PRZYGOTOWANIE",
            "running": f"RENDER {pct_r}",
            "finalizing": f"FINALIZACJA {pct_r}",
            "done": "GOTOWY",
            "error": "BŁĄD",
            "cancelled": "ANULOWANO",
            "interrupted": "PRZERWANO",
        }
        r_label = status_map.get(r, r.upper())

        yt_label = ""
        if job.yt_enabled:
            upload_map = {
                "idle": "",
                "waiting": " | YT: czeka",
                "running": f" | YT: {pct_u}",
                "done": " | YT: ✓",
                "error": " | YT: błąd",
                "interrupted": " | YT: przerwano",
            }
            yt_label = upload_map.get(up, "")

        if r == "done":
            elapsed_val = getattr(job, "render_elapsed_s", 0.0)
            if elapsed_val <= 0 and job.render_finished_at and job.render_started_at:
                elapsed_val = max(0.0, job.render_finished_at - job.render_started_at)
            time_str = self._fmt_time(elapsed_val) if elapsed_val > 0 else "--:--"

            avg_fps = getattr(job, "average_fps", 0.0)
            fps_str = f"{avg_fps:.1f} FPS" if (avg_fps and avg_fps > 0) else "brak danych"

            avg_qp = getattr(job, "average_qp", None)
            qp_str = f"{avg_qp:.1f}" if avg_qp is not None else "brak danych"

            if getattr(job, "is_expanded", False):
                prefix = "▼ "
                details = (
                    f"\n   |_ Lokalizacja: {job.output_path}"
                    f"\n   |_ Czas: {time_str}"
                    f"\n   |_ Średnia wydajność: {fps_str}"
                    f"\n   |_ Średnie QP: {qp_str}"
                )
            else:
                prefix = "▶ "
                details = ""
            return f"{prefix}{r_label}{yt_label}  {name}{details}"

        return f"{r_label}{yt_label}  {name}"

    def _set_queue_btn_state(self, *, running: bool) -> None:
        self.btn_queue_start.setEnabled(not running)
        self.btn_queue_pause.setEnabled(running)
        if hasattr(self, "btn_queue_stop"):
            self.btn_queue_stop.setEnabled(True)

    def _on_add_to_queue(self) -> None:
        """Snapshot bieżących ustawień i dodaj do kolejki."""
        self._init_export_queue()
        q = self._export_queue
        if q is None:
            return
        ctrl = self._controller
        import copy
        # Snapshot opcji renderowania
        options = self._build_options_from_gui()
        options.pop("output", None)
        # Snapshot ścieżek
        video_paths = [str(p) for p in (getattr(ctrl, "video_paths", None) or [])]
        if not video_paths:
            vp = getattr(ctrl, "video_path", None)
            if vp:
                video_paths = [str(vp)]
        if not video_paths:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Kolejka", "Nie wybrano pliku wideo.")
            return

        fit_path = str(getattr(ctrl, "fit_path", "") or getattr(getattr(ctrl, "telemetry", None), "fit_path", "") or "")
        gpx_path = str(getattr(ctrl, "gpx_path", "") or "")

        # Snapshot layoutu
        layout_snap = {}
        if hasattr(ctrl, "layout"):
            try:
                layout_snap = copy.deepcopy(ctrl.layout)
            except Exception:
                pass

        output = self.edit_output.text().strip() or "output_h265.mp4"

        job = ExportJob(
            video_paths=video_paths,
            fit_path=fit_path,
            gpx_path=gpx_path,
            layout=layout_snap,
            options=options,
            output_path=output,
            yt_enabled=self.chk_yt_enabled.isChecked(),
            yt_title=self.edit_yt_title.text().strip(),
            yt_privacy=self.cmb_yt_privacy.currentData() or "private",
            yt_description=self.edit_yt_desc.text().strip(),
        )
        q.add_job(job)
        self._refresh_queue_ui()
        print(f"[ExportQueue] Job added: {job.job_id} output={job.output_path}", flush=True)

    def _on_queue_start(self) -> None:
        """Uruchom/wznów kolejkę."""
        self._init_export_queue()
        if self._export_queue:
            self._export_queue.start()

    def _on_queue_pause(self) -> None:
        """Wstrzymaj kolejkę."""
        if self._export_queue:
            self._export_queue.pause()

    def _on_queue_remove(self) -> None:
        """Usuń zaznaczone joby z kolejki."""
        q = self._export_queue
        if q is None:
            return
        selected_items = self.queue_list.selectedItems()
        if not selected_items:
            return
            
        any_active_skipped = False
        for item in selected_items:
            job_id = item.data(Qt.UserRole)
            if not job_id:
                continue
            removed = q.remove_job(job_id)
            if not removed:
                any_active_skipped = True
                
        if any_active_skipped:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Kolejka",
                "Nie można usunąć zadania, które jest aktualnie renderowane."
            )
        self._refresh_queue_ui()

    def _on_queue_stop(self) -> None:
        """Zatrzymaj kolejkę i natychmiast anuluj aktywny render (STOP)."""
        self._init_export_queue()
        if self._export_queue:
            self._export_queue.pause()
        if self._rendering or self._cancelling:
            self._on_cancel()
        self._set_queue_btn_state(running=False)
        self._refresh_queue_ui()

    def _on_queue_export(self) -> None:
        """Eksportuj zadania kolejki do pliku *.telemqueue.json."""
        self._init_export_queue()
        if not self._export_queue:
            return
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(
            self, "Eksportuj kolejkę", "export_queue.telemqueue.json",
            "TeleM Queue (*.telemqueue.json);;JSON (*.json);;Wszystkie pliki (*.*)"
        )
        if not path:
            return
        try:
            self._export_queue.export_to_file(Path(path))
            QMessageBox.information(self, "Eksport kolejki", f"Pomyślnie wyeksportowano kolejkę do:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Błąd eksportu kolejki", f"Nie udało się zapisać kolejki:\n{exc}")

    def _on_queue_import(self) -> None:
        """Importuj zadania do kolejki z pliku *.telemqueue.json."""
        self._init_export_queue()
        if not self._export_queue:
            return
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            self, "Importuj kolejkę", "",
            "TeleM Queue (*.telemqueue.json);;JSON (*.json);;Wszystkie pliki (*.*)"
        )
        if not path:
            return
        try:
            count = self._export_queue.import_from_file(Path(path), mode="append")
            self._refresh_queue_ui()
            QMessageBox.information(self, "Import kolejki", f"Pomyślnie zaimportowano {count} zadań.")
        except Exception as exc:
            QMessageBox.critical(self, "Błąd importu kolejki", f"Nie udało się zaimportować kolejki:\n{exc}")

    def _build_inout_bar(self) -> QHBoxLayout:
        """Pasek narzędzi zakresu eksportu: IN / OUT / Wyczyść z krokami klatkowymi."""
        row = QHBoxLayout()
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        # ── IN (START) ──
        self.btn_in = QPushButton("IN")
        self.btn_in.setFixedHeight(26)
        self.btn_in.setToolTip("Ustaw punkt początku eksportu (IN) na aktualnej pozycji")
        self.btn_in.clicked.connect(self._on_set_in)

        self.btn_in_prev = QPushButton("[-1f]")
        self.btn_in_prev.setFixedHeight(26)
        self.btn_in_prev.setFixedWidth(38)
        self.btn_in_prev.setToolTip("Cofnij punkt IN o dokładnie 1 klatkę")
        self.btn_in_prev.clicked.connect(lambda: self._on_step_in(-1))

        self.btn_in_next = QPushButton("[+1f]")
        self.btn_in_next.setFixedHeight(26)
        self.btn_in_next.setFixedWidth(38)
        self.btn_in_next.setToolTip("Przesuń punkt IN naprzód o dokładnie 1 klatkę")
        self.btn_in_next.clicked.connect(lambda: self._on_step_in(1))

        self.lbl_in = QLabel("IN: --:--")
        self.lbl_in.setStyleSheet("color: #ffd75e; font-weight: bold;")

        # ── OUT (END) ──
        self.btn_out = QPushButton("OUT")
        self.btn_out.setFixedHeight(26)
        self.btn_out.setToolTip("Ustaw punkt końca eksportu (OUT) na aktualnej pozycji")
        self.btn_out.clicked.connect(self._on_set_out)

        self.btn_out_prev = QPushButton("[-1f]")
        self.btn_out_prev.setFixedHeight(26)
        self.btn_out_prev.setFixedWidth(38)
        self.btn_out_prev.setToolTip("Cofnij punkt OUT o dokładnie 1 klatkę")
        self.btn_out_prev.clicked.connect(lambda: self._on_step_out(-1))

        self.btn_out_next = QPushButton("[+1f]")
        self.btn_out_next.setFixedHeight(26)
        self.btn_out_next.setFixedWidth(38)
        self.btn_out_next.setToolTip("Przesuń punkt OUT naprzód o dokładnie 1 klatkę")
        self.btn_out_next.clicked.connect(lambda: self._on_step_out(1))

        self.lbl_out = QLabel("OUT: --:--")
        self.lbl_out.setStyleSheet("color: #ff8a8a; font-weight: bold;")

        self.lbl_range_len = QLabel("Zakres: --:--")
        self.lbl_range_len.setStyleSheet("color: #aaa;")

        self.btn_clear_range = QPushButton("Wyczyść zakres")
        self.btn_clear_range.setFixedHeight(26)
        self.btn_clear_range.setToolTip("Usuń zaznaczony zakres IN/OUT")
        self.btn_clear_range.clicked.connect(self._on_clear_range)

        row.addWidget(self.btn_in)
        row.addWidget(self.btn_in_prev)
        row.addWidget(self.btn_in_next)
        row.addWidget(self.lbl_in)
        row.addSpacing(10)
        row.addWidget(self.btn_out)
        row.addWidget(self.btn_out_prev)
        row.addWidget(self.btn_out_next)
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
        s.sig_render_state.connect(self._on_render_state)
        s.sig_export_preview_ready.connect(self._on_export_preview_ready)
        s.sig_render_finished.connect(self._on_finished)
        s.sig_render_stopped.connect(self._on_stopped)
        s.sig_error.connect(self._on_error)
        s.sig_video_duration_ready.connect(self._on_video_duration_ready)
        s.sig_amd_decode_mode_restored.connect(self._on_amd_decode_mode_restored)
        s.sig_amd_encoder_quality_restored.connect(self._on_amd_encoder_quality_restored)
        s.sig_default_export_name_ready.connect(self._on_default_export_name_ready)
        s.sig_video_info_ready.connect(self._on_video_info_ready)

    def _on_video_info_ready(self, info: str) -> None:
        """Apply the source-resolution part of the capability gate."""
        match = re.match(r"\s*(\d+)x(\d+)\b", str(info or ""))
        if match:
            self._source_dimensions = (int(match.group(1)), int(match.group(2)))
            if hasattr(self, "_update_backend_visibility"):
                self._update_backend_visibility()

    def _connect_preview_signals(self) -> None:
        """Podłącz sygnały podglądu — tylko gdy zakładka posiada podgląd.

        W trybie współdzielonym sygnały podglądu podłącza MainWindow (raz).
        """
        s = self.signals
        s.sig_preview_frame_ready.connect(self.video_preview.on_frame_ready)
        s.sig_bboxes_ready.connect(self.video_preview.set_bboxes)
        s.sig_video_duration_ready.connect(self.video_preview.on_duration_ready)
        s.sig_seek_position.connect(self.video_preview._on_seek_position)

    def set_controller(self, controller: object) -> None:
        """Ustaw referencję do kontrolera (wywoływane z MainWindow)."""
        self._controller = controller
        self._gpu_capabilities = getattr(controller, "gpu_capabilities", None)
        if hasattr(self, "_update_backend_visibility"):
            self._update_backend_visibility()
        try:
            setattr(controller, "preview_diagnostics_provider", self.export_preview_diagnostics)
        except Exception:
            pass
        if self._owns_preview:
            self.video_preview.set_controller(controller)
        # Autoload kolejki eksportu przy starcie aplikacji (QUEUE_AUTOLOAD_ON_START=True)
        self._init_export_queue()

    # ═════════════════════════════════════════════════════════════════════
    # Zakres eksportu IN/OUT
    # ═════════════════════════════════════════════════════════════════════

    def _fmt_time(self, secs: float) -> str:
        if secs is None or not (0 <= secs <= 3600000):
            return "--:--"
        secs = max(0, int(secs))
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _get_fps(self) -> float:
        fps = 30.0
        if self._controller is not None:
            fps = float(getattr(self._controller, "fps", 30.0) or 30.0)
        return fps if fps > 0 else 30.0

    def _get_total_frames(self) -> int:
        fps = self._get_fps()
        dur = self._duration_s()
        return max(1, int(round(dur * fps)))

    def _duration_s(self) -> float:
        if self._controller is None:
            return 0.0
        return float(getattr(self._controller, "video_duration_s", 0.0) or 0.0)

    def _current_orig_pos(self) -> float:
        """Aktualna pozycja źródłowa z neutralnego podglądu Export."""
        sb = self.video_preview.seek_bar
        return sb.get_position()

    def _on_set_in(self) -> None:
        """Ustaw punkt IN na aktualnej pozycji w domenie klatek."""
        dur = self._duration_s()
        if dur <= 0:
            return
        fps = self._get_fps()
        pos = min(max(0.0, self._current_orig_pos()), dur)
        self._in_frame = int(round(pos * fps))
        self._apply_in_frame()

    def _on_step_in(self, delta: int) -> None:
        """Krok klatkowy punktu IN w domenie całkowitej liczby klatek."""
        dur = self._duration_s()
        if dur <= 0:
            return
        fps = self._get_fps()
        if self._in_frame is None:
            pos = min(max(0.0, self._current_orig_pos()), dur)
            self._in_frame = int(round(pos * fps))
        total_frames = self._get_total_frames()
        new_frame = max(0, self._in_frame + int(delta))
        if self._out_frame is not None:
            new_frame = min(new_frame, max(0, self._out_frame - 1))
        else:
            new_frame = min(new_frame, total_frames - 1)
        self._in_frame = new_frame
        self._apply_in_frame()
        if self._in_orig is not None:
            self.signals.sig_seek_changed.emit(self._in_orig)

    def _apply_in_frame(self) -> None:
        fps = self._get_fps()
        dur = self._duration_s()
        if self._in_frame is None:
            return
        pos = self._in_frame / fps
        if self._in_orig is not None and self._in_orig > 0:
            self._remove_boundary(0.0, self._in_orig)
        self._in_orig = pos
        if pos > 0:
            self._add_boundary(0.0, pos)
        if (self._out_frame is not None and self._out_frame <= self._in_frame) or (self._out_orig is not None and self._out_orig <= pos):
            self._clear_range()
            return
        self._update_inout_labels()

    def _on_set_out(self) -> None:
        """Ustaw punkt OUT na aktualnej pozycji w domenie klatek."""
        dur = self._duration_s()
        if dur <= 0:
            return
        fps = self._get_fps()
        pos = min(max(0.0, self._current_orig_pos()), dur)
        self._out_frame = int(round(pos * fps))
        self._apply_out_frame()

    def _on_step_out(self, delta: int) -> None:
        """Krok klatkowy punktu OUT w domenie całkowitej liczby klatek."""
        dur = self._duration_s()
        if dur <= 0:
            return
        fps = self._get_fps()
        if self._out_frame is None:
            pos = min(max(0.0, self._current_orig_pos()), dur)
            self._out_frame = int(round(pos * fps))
        total_frames = self._get_total_frames()
        new_frame = self._out_frame + int(delta)
        if self._in_frame is not None:
            new_frame = max(self._in_frame + 1, new_frame)
        else:
            new_frame = max(1, new_frame)
        new_frame = min(total_frames, new_frame)
        self._out_frame = new_frame
        self._apply_out_frame()
        if self._out_orig is not None:
            self.signals.sig_seek_changed.emit(self._out_orig)

    def _apply_out_frame(self) -> None:
        fps = self._get_fps()
        dur = self._duration_s()
        if self._out_frame is None:
            return
        pos = self._out_frame / fps
        if self._out_orig is not None and self._out_orig < dur:
            self._remove_boundary(self._out_orig, dur)
        self._out_orig = pos
        if pos < dur:
            self._add_boundary(pos, dur)
        if (self._in_frame is not None and self._in_frame >= self._out_frame) or (self._in_orig is not None and self._in_orig >= pos):
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
        self._in_frame = None
        self._out_frame = None
        self._update_inout_labels()

    def _on_clear_range(self) -> None:
        self._clear_range()

    def _update_inout_labels(self) -> None:
        if self._in_orig is not None:
            self.lbl_in.setText(f"IN: {self._fmt_time(self._in_orig)}")
            if self._in_frame is not None:
                self.lbl_in.setToolTip(f"Punkt IN: {self._fmt_time(self._in_orig)} (klatka: {self._in_frame})")
        else:
            self.lbl_in.setText("IN: --:--")
            self.lbl_in.setToolTip("")

        if self._out_orig is not None:
            self.lbl_out.setText(f"OUT: {self._fmt_time(self._out_orig)}")
            if self._out_frame is not None:
                self.lbl_out.setToolTip(f"Punkt OUT: {self._fmt_time(self._out_orig)} (klatka: {self._out_frame})")
        else:
            self.lbl_out.setText("OUT: --:--")
            self.lbl_out.setToolTip("")

        if self._in_orig is not None and self._out_orig is not None:
            self.lbl_range_len.setText(
                f"Zakres: {self._fmt_time(self._out_orig - self._in_orig)}"
            )
        else:
            self.lbl_range_len.setText("Zakres: --:--")

    def _on_video_duration_ready(self, _duration: float) -> None:
        """Nowy film — zresetuj zakres IN/OUT (nowa oś czasu)."""
        self._clear_range()
        self._user_edited_output = False

    def _on_output_text_edited(self, _text: str) -> None:
        self._user_edited_output = True

    def _on_default_export_name_ready(self, filename: str) -> None:
        if not self._user_edited_output and filename:
            self.edit_output.setText(filename)

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
        curr = self.edit_output.text().strip()
        if curr and os.path.isabs(curr):
            initial_path = curr
        elif curr:
            initial_dir = getattr(self, "_last_output_dir", None) or os.getcwd()
            initial_path = os.path.join(initial_dir, os.path.basename(curr))
        else:
            initial_dir = getattr(self, "_last_output_dir", None) or os.getcwd()
            initial_path = os.path.join(initial_dir, "output_h265.mp4")

        path, _ = QFileDialog.getSaveFileName(
            self, "Plik wyjściowy", initial_path, "MP4 (*.mp4);;Wszystkie pliki (*.*)",
        )
        if path:
            self._last_output_dir = os.path.dirname(path)
            self._user_edited_output = True
            self.edit_output.setText(path)

    def _log_preview_resource_snapshot(self, label: str) -> None:
        """Emit one process/resource snapshot for Preview lifecycle forensics."""
        with self._preview_lock:
            if label in self._preview_snapshot_labels:
                return
            self._preview_snapshot_labels.add(label)
            stop_event = self._preview_stop_event
            worker = self._preview_worker_thread
            pending = self._preview_pending_ts
            decode_active = self._preview_decode_active
            preview_generation = self._preview_generation_id
            request_seq = self._preview_request_seq
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info()
            private_bytes = getattr(mem, "private", None)
            children = proc.children(recursive=True)
            child_rows = []
            for child in children:
                try:
                    cmd = " ".join(child.cmdline())
                except Exception:
                    cmd = ""
                name = (child.name() or "").lower()
                if "ffmpeg" in name or "ffmpeg" in cmd.lower():
                    child_rows.append({"pid": child.pid, "alive": child.is_running()})
            handle_count = getattr(proc, "num_handles", lambda: None)()
            rss = int(mem.rss)
            commit = int(private_bytes if private_bytes is not None else mem.vms)
            thread_count = int(proc.num_threads())
        except Exception:
            # psutil is optional in the production install.  Keep the
            # snapshot useful on a bare Windows/Python environment too.
            rss = commit = handle_count = None
            child_rows = []
            thread_count = sum(1 for _ in threading.enumerate())
            try:
                import ctypes
                class _ProcessMemoryCounters(ctypes.Structure):
                    _fields_ = [
                        ("cb", ctypes.c_uint32),
                        ("PageFaultCount", ctypes.c_uint32),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t),
                    ]
                counters = _ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.psapi.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb,
                )
                rss = int(counters.WorkingSetSize)
                commit = int(counters.PrivateUsage)
                handles = ctypes.c_uint32()
                if ctypes.windll.kernel32.GetProcessHandleCount(handle, ctypes.byref(handles)):
                    handle_count = int(handles.value)
            except Exception:
                pass
            if not rss or not commit:
                try:
                    probe = subprocess.run(
                        [
                            "powershell", "-NoProfile", "-Command",
                            "& { $p=Get-Process -Id " + str(os.getpid()) +
                            "; [pscustomobject]@{rss=$p.WorkingSet64; private=$p.PrivateMemorySize64; "
                            "handles=$p.Handles; threads=$p.Threads.Count} | ConvertTo-Json -Compress }",
                        ], capture_output=True, text=True, timeout=2.0,
                    )
                    if probe.returncode == 0 and probe.stdout.strip():
                        ps = json.loads(probe.stdout)
                        rss = int(ps.get("rss") or rss or 0)
                        commit = int(ps.get("private") or commit or 0)
                        handle_count = int(ps.get("handles") or handle_count or 0)
                        thread_count = int(ps.get("threads") or thread_count or 0)
                except Exception:
                    pass

        try:
            from src.video_helpers import _CV2_CAP_CACHE
            capture_cache = {
                "count": len(_CV2_CAP_CACHE),
                "paths": list(_CV2_CAP_CACHE.keys()),
            }
        except Exception:
            capture_cache = {"count": None, "paths": []}
        ctrl = self._controller
        mpv = getattr(ctrl, "mpv_player", None) if ctrl is not None else None
        media_player = getattr(ctrl, "media_player", None) if ctrl is not None else None
        holder = getattr(ctrl, "render_process_holder", {}) if ctrl is not None else {}
        process = holder.get("process") if isinstance(holder, dict) else None
        pump_keys = [str(k) for k in holder if "pump" in str(k).lower()] if isinstance(holder, dict) else []
        producer_keys = [str(k) for k in holder if "producer" in str(k).lower()] if isinstance(holder, dict) else []
        data = {
            "label": label,
            "pid": os.getpid(),
            "rss_bytes": rss,
            "private_or_commit_bytes": commit,
            "thread_count": thread_count,
            "preview_threads": [
                t.name for t in threading.enumerate()
                if t.name.startswith("TeleM-ExportPreview-")
            ],
            "ffmpeg_child_pids": child_rows,
            "opencv_decoder_cache": capture_cache,
            "opencv_active_decoders": decode_active,
            "mpv_state": {
                "exists": mpv is not None,
                "type": type(mpv).__name__ if mpv is not None else None,
            },
            "qmedia_state": {
                "exists": media_player is not None,
                "type": type(media_player).__name__ if media_player is not None else None,
                "state": str(media_player.playbackState()) if media_player is not None and hasattr(media_player, "playbackState") else None,
            },
            "d3d11_mf_preview_resources": 0 if self._export_preview_lightweight else "idle-player-owned",
            "open_handles": handle_count,
            "preview_generation_id": preview_generation,
            "render_generation_id": self._render_generation_id,
            "preview_stop_event": {"id": id(stop_event), "set": stop_event.is_set()},
            "render_cancel_event": {
                "id": id(getattr(ctrl, "render_cancel_event", None)),
                "set": bool(getattr(getattr(ctrl, "render_cancel_event", None), "is_set", lambda: False)()),
            },
            "pending_timestamp": pending,
            "request_sequence": request_seq,
            "preview_worker": {
                "alive": bool(worker is not None and worker.is_alive()),
                "id": id(worker) if worker is not None else None,
            },
            "producer_state": {"holder_keys": producer_keys},
            "pump_state": {"holder_keys": pump_keys},
            "ffmpeg_render_state": {
                "pid": getattr(process, "pid", None),
                "alive": bool(process is not None and process.poll() is None),
            },
        }
        print("[PREVIEW RESOURCE SNAPSHOT]", flush=True)
        print(json.dumps(data, sort_keys=True, default=str), flush=True)

    def _build_options_from_gui(self) -> dict:
        """Zbierz bieżące opcje renderowania z kontrolek GUI."""
        return {
            "encoder": self.cmb_encoder.currentText(),
            "render_mode": self.cmb_render_mode.currentData() or "gpu",
            "resolution": self.cmb_resolution.currentText(),
            "rotation": self.cmb_rotation.currentText(),
            "update_rate": self.cmb_update_rate.currentText(),
            "hud_resolution_scale": self.cmb_hud_resolution.currentText(),
            "amd_decode_mode": self.cmb_amd_decode.currentData() or "gpu",
            "amd_encoder_quality": self.cmb_amd_quality.currentData() or "FAST",
            "bitrate": self.edit_bitrate.text().strip(),
            "output": self.edit_output.text().strip(),
            "nvidia_backend": self.cmb_nvidia_backend.currentData() or "legacy_cuda",
            "nvidia_codec": self.cmb_nvidia_codec.currentText(),
            "nvidia_quality": self.cmb_nvidia_quality.currentText(),
            "intel_codec": self.cmb_intel_codec.currentData() or "av1",
            "encoder_profile": (
                self.cmb_encoder_profile.currentData()
                if hasattr(self, "cmb_encoder_profile")
                else "balanced"
            ) or "balanced",
            "compression_analysis": self.chk_compression_analysis.isChecked(),
            "_gui_hud_preview_checkbox": self.chk_hud_preview.isChecked(),
        }

    def _on_render(self) -> None:
        try:
            from src.startup_timeline import StartupTimelineTracker
            _tracker = StartupTimelineTracker.get_instance()
            _tracker.mark_event("GUI Render clicked")
            _tracker.start_stage("GUI dispatch")
        except Exception:
            pass
        if self._rendering or self._cancelling:
            return
        options = self._build_options_from_gui()
        self._start_render(options, job=None)

    def _start_export_preview_generation(self) -> None:
        """Create a completely fresh Preview generation for one render."""
        with self._preview_lock:
            self._preview_stop_event = threading.Event()
            self._preview_generation_id += 1
            self._preview_pending_ts = None
            self._preview_request_seq += 1
            self._preview_worker_active = False
            self._preview_busy = False
            self._preview_worker_thread = None
            self._preview_decode_active = 0
            self._gpu_tap_pending_payload = None
            self._gpu_tap_signal_pending = False
        self._preview_failed = False
        self._preview_fault_injected = False
        self._preview_update_times_ms = []
        self._preview_worker_starts = 0
        self._preview_resources_reported = False
        self._last_continuous_hevc_stats = {}
        self._preview_cached_video_frame = None
        self._preview_last_video_decode_ts = None
        self._preview_had_lifecycle = self.chk_hud_preview.isChecked()
        self._pending_hud_switch_log = False

    def _stop_export_preview(self, reason: str, *, wait: bool = True) -> None:
        """Stop Preview and release all resources owned by its generation."""
        with self._preview_lock:
            stop_event = self._preview_stop_event
            stop_event.set()
            self._preview_pending_ts = None
            self._preview_request_seq += 1
            worker = self._preview_worker_thread
        if (
            wait and worker is not None and worker is not threading.current_thread()
        ):
            worker.join(timeout=3.0)
        alive = bool(worker is not None and worker.is_alive())
        # The AMD export-preview path uses per-snapshot VideoCapture objects,
        # but idle preview may still have an older cached capture. Closing it
        # here makes Preview OFF a real teardown boundary.
        try:
            from src.video_helpers import clear_capture_cache
            clear_capture_cache()
        except Exception as exc:
            print(f"[PREVIEW RESOURCE RELEASE] reason={reason} error={exc}", flush=True)
        self._preview_cached_video_frame = None
        self._preview_last_video_decode_ts = None
        session = self._amd_export_preview_session
        if session is not None:
            try:
                session.stop(reason)
            except Exception as exc:
                print(f"[EXPORT PREVIEW FFMPEG ERROR] stop failed: {exc}", flush=True)
        with self._preview_lock:
            if self._preview_worker_thread is worker and not alive:
                self._preview_worker_thread = None
            self._preview_worker_active = alive
            self._preview_busy = alive
        gc.collect()
        print(
            f"[PREVIEW RESOURCE RELEASE] reason={reason} worker_alive={int(alive)}",
            flush=True,
        )

    def _on_preview_checkbox_changed(self, state: int) -> None:
        """Preview OFF is an explicit teardown, not merely a rate limiter."""
        if bool(state):
            if self._rendering and self._preview_stop_event.is_set():
                self._start_export_preview_generation()
            return
        if self._preview_had_lifecycle or self._preview_worker_active:
            self._log_preview_resource_snapshot("D_after_preview_off")
        self._stop_export_preview("checkbox_off")

    def _on_cancel(self) -> None:
        if not self._rendering or self._cancelling:
            return
        # P1-B FIX: CANCELLING state. Do NOT call _end_render() here.
        # Wait for worker thread to confirm exit via sig_render_stopped / sig_error.
        self._cancelling = True
        self.btn_render.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        current = self._render_state or RenderProgressState(
            generation_id=self._render_generation_id,
            state="cancelling",
            frame=0,
            total_frames=self._render_total,
            elapsed_s=time.monotonic() - self._render_start if self._render_start else 0.0,
        )
        self._on_render_state(replace(
            current,
            state="cancelling",
            cancel_requested=True,
        ))
        # The request carries the session identity; the legacy notification
        # remains for old observers but is not connected to the controller.
        self.signals.sig_render_cancel_requested.emit(
            RenderCancelRequest(
                generation_id=self._render_generation_id,
                reason=RenderCancelReason.USER_CANCEL,
                source="GUI_BUTTON",
            )
        )
        self.signals.sig_render_cancelled.emit()

    def _on_stopped(self) -> None:
        """Potwierdzenie zakończenia workera po anulowaniu -> powrót do IDLE."""
        if not self._rendering:
            return
        if self._render_state_enabled and not self._cancelling:
            return
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

    def _on_render_state(self, snapshot: RenderProgressState) -> None:
        """Apply the one canonical export snapshot to this tab."""
        if not isinstance(snapshot, RenderProgressState):
            return
        if snapshot.generation_id != self._render_generation_id:
            return
        if (
            not self._rendering
            and not snapshot.completed
            and not snapshot.cancelled
            and not snapshot.failed
        ):
            return
        self._render_state = snapshot
        self._render_total = max(self._render_total, snapshot.total_frames)
        if snapshot.global_percent > self._render_target:
            self._render_target = min(99.9, snapshot.global_percent)
        is_indeterminate = getattr(snapshot, "progress_mode", "determinate") == "indeterminate"
        if is_indeterminate:
            if not getattr(self, "_is_indeterminate", False):
                self._is_indeterminate = True
                self.progress.setRange(0, 0)
        else:
            if getattr(self, "_is_indeterminate", False):
                self._is_indeterminate = False
                self.progress.setRange(0, 100)
                self.progress.setValue(int(round(self._render_display)))
        # Section 7: Routing postępu do kolejki z jedynego kanonicznego źródła (sig_render_state)
        if self._export_queue and getattr(self, "_active_queue_job_id", None):
            pct = max(0.0, min(1.0, snapshot.global_percent / 100.0))
            self._export_queue.notify_render_progress(
                self._active_queue_job_id, pct, phase=snapshot.phase or snapshot.state,
            )
        if snapshot.completed:
            status = "Gotowe"
        elif snapshot.cancelled:
            status = "Anulowano"
        elif snapshot.failed:
            status = "Błąd"
        elif snapshot.cancel_requested:
            status = "Anulowanie..."
        elif snapshot.state == "finalizing" or snapshot.phase == "finalize":
            status = snapshot.finalization_stage or "Finalizacja..."
        elif snapshot.state == "preparing" or snapshot.phase == "prep":
            status = snapshot.prep_label or "Przygotowywanie HUD..."
        elif snapshot.total_frames > 0 and snapshot.frame >= snapshot.total_frames:
            status = snapshot.finalization_stage or "Finalizacja..."
        else:
            status = "Renderowanie..."
        if snapshot.state == "finalizing" or snapshot.phase == "finalize":
            self.lbl_stats.setText(format_render_progress_status(snapshot))
        else:
            eta = None if snapshot.eta_s is None else self._fmt_time(snapshot.eta_s)
            item_label = "HUD" if snapshot.state == "preparing" else "Frame"
            completed_val = snapshot.prep_done if snapshot.state == "preparing" and snapshot.prep_total > 0 else snapshot.frame
            total_val = snapshot.prep_total if snapshot.state == "preparing" and snapshot.prep_total > 0 else snapshot.total_frames
            qp_val = getattr(snapshot, "qp", None)
            if qp_val is None:
                qp_val = getattr(snapshot, "avg_qp", None)
            self._set_stats(
                completed_val, total_val, snapshot.elapsed_s,
                snapshot.fps, status, final_eta=eta,
                item_label=item_label,
                is_indeterminate=is_indeterminate,
                qp=qp_val,
                global_pct=snapshot.global_percent,
            )
        comp_txt = getattr(snapshot, "compression_text", "")
        if comp_txt:
            if snapshot.completed:
                comp_txt = re.sub(r"\s*\|\s*q teraz:\s*[\d\.]+", "", comp_txt)
            self.lbl_compression_stats.setText(comp_txt)
            self.lbl_compression_stats.setVisible(True)
        if snapshot.completed:
            self._is_indeterminate = False
            self.progress.setRange(0, 100)
            self._render_target = 100.0
            self._render_display = 100.0
            self.progress.setValue(100)
            self._end_render()
        elif snapshot.cancelled or snapshot.failed:
            self._end_render()

    def _on_render_progress(self, completed: int, total: int, elapsed: float,
                            fps: float, hud_state) -> None:
        """Rzeczywisty progress pipeline'u (completed/total, nie timer).

        Obsługuje dwa kontrakty na tym samym sygnale:
        - raport fazy ({"phase": "prep"|"finalize", "pct", "label"}) — mapowany
          na zakres wspólnego paska (Przygotowywanie HUD / Finalizacja);
        - raport klatki (completed/total, {"frame","ts"}) — mapowany na zakres
          10..98% wspólnego paska.
        """
        if self._cancelling and not (
            isinstance(hud_state, dict) and hud_state.get("phase") == "finalize"
        ):
            return

        # Faza finalizacji (opróżnianie klatek, zamykanie enkodera, zapis MP4, postprocess)
        if self._render_state_enabled:
            if (
                hud_state is not None
                and isinstance(hud_state, dict)
                and "ts" in hud_state
                and self.chk_hud_preview.isChecked()
            ):
                self._hud_ts = hud_state.get("ts")
                now = time.monotonic()
                if now - self._last_preview_time >= self._EXPORT_PREVIEW_INTERVAL_S:
                    self._last_preview_time = now
                    self._trigger_async_preview(self._hud_ts)
            return

        if hud_state is not None and isinstance(hud_state, dict) and hud_state.get("phase") == "finalize":
            if not self._in_finalize:
                self._in_finalize = True
                self._finalize_start_mono = time.monotonic()
            self._finalize_stage = str(hud_state.get("finalize_stage", hud_state.get("label", "Finalizacja: zapis MP4")))
            self._finalize_drain_pct = hud_state.get("drain_pct")
            self._finalize_file_size = int(hud_state.get("file_size_bytes", 0) or 0)
            self._finalize_write_speed = float(hud_state.get("write_speed_mbps", 0.0) or 0.0)
            self._finalize_stall_warning = bool(hud_state.get("stall_warning", False))
            self._finalize_stall_seconds = int(hud_state.get("stall_seconds", 0) or 0)

            if "global_pct" in hud_state:
                overall = max(self._render_target, float(hud_state.get("global_pct", 0.0)))
            elif self._finalize_drain_pct is not None:
                overall = 95.0 + (max(0.0, min(100.0, float(self._finalize_drain_pct))) / 100.0) * 3.0
            else:
                overall = max(self._render_target, 98.0)
            self._render_target = min(99.9, overall)
            self._update_finalize_status_label()
            return

        qp_val = None
        if isinstance(hud_state, dict):
            for k in ("mean_qp", "avg_qp", "qp_avg", "qp", "current_qp"):
                v = hud_state.get(k)
                if v is not None:
                    try:
                        fv = float(v)
                        if fv > 0:
                            qp_val = fv
                            break
                    except (ValueError, TypeError):
                        pass

        if hud_state is not None and isinstance(hud_state, dict) and "global_pct" in hud_state:
            overall = max(self._render_target, float(hud_state.get("global_pct", 0.0)))
            self._render_target = min(99.9, overall)
            phase = hud_state.get("phase")
            status = str(hud_state.get("label", "Renderowanie..."))
            if phase == "render":
                self._render_total = total or self._render_total
                item_label = "Frame"
            else:
                completed = hud_state.get("work_done", completed)
                total = hud_state.get("work_total", total)
                item_label = "HUD"
            self._set_stats(completed, total, elapsed, fps, status, item_label=item_label, qp=qp_val)
            if phase == "render" and "ts" in hud_state and self.chk_hud_preview.isChecked():
                self._hud_ts = hud_state.get("ts")
                now = time.monotonic()
                if now - self._last_preview_time >= self._EXPORT_PREVIEW_INTERVAL_S:
                    self._last_preview_time = now
                    self._trigger_async_preview(self._hud_ts)
            return
        if hud_state is not None and isinstance(hud_state, dict) and "phase" in hud_state:
            self._on_render_phase(hud_state, elapsed)
            return

        if total > 0:
            self._render_total = total
        total = self._render_total or total or 1
        frac = min(1.0, completed / total)
        overall = self._RENDER_START + frac * (self._RENDER_END - self._RENDER_START)
        if completed >= total:
            # Wszystkie klatki wypisane — finalizacja (mux/flush) jeszcze trwa
            overall = min(overall, self._RENDER_END)
            status = "Finalizacja..."
        else:
            status = "Renderowanie..."
        # Nigdy nie cofaj paska
        if overall > self._render_target:
            self._render_target = overall
        self._set_stats(completed, total, elapsed, fps, status, qp=qp_val)

        # HUD Preview — latest-state, tylko dla raportów klatek (mają "ts")
        if hud_state is not None and isinstance(hud_state, dict) and "ts" in hud_state and self.chk_hud_preview.isChecked():
            self._hud_ts = hud_state.get("ts")
            now = time.monotonic()
            if now - self._last_preview_time >= self._EXPORT_PREVIEW_INTERVAL_S:
                self._last_preview_time = now
                self._trigger_async_preview(self._hud_ts)

    def _update_finalize_status_label(self) -> None:
        """Sformatuj czytelny status finalizacji bez fałszywego ETA, z timerem i rozmiarem/MB/s."""
        if not self._in_finalize:
            return
        now = time.monotonic()
        elapsed_s = max(0.0, (now - self._finalize_start_mono) if self._finalize_start_mono is not None else 0.0)
        time_txt = self._fmt_time(elapsed_s)

        sz = self._finalize_file_size
        if sz >= 1024 * 1024 * 1024:
            size_txt = f"{sz / (1024.0 ** 3):.1f} GB"
        elif sz >= 1024 * 1024:
            size_txt = f"{sz / (1024.0 ** 2):.1f} MB"
        elif sz > 0:
            size_txt = f"{sz / 1024.0:.0f} KB"
        else:
            size_txt = "-- GB"

        speed_txt = f"{self._finalize_write_speed:.0f} MB/s"

        if self._finalize_stall_warning:
            text = (
                f"Finalizacja trwa — brak postępu zapisu od {self._finalize_stall_seconds} s"
                f"   |   {time_txt}   |   {size_txt}   |   {speed_txt}"
            )
        elif self._finalize_drain_pct is not None or "opróżnianie" in (self._finalize_stage or ""):
            drain_txt = f"{self._finalize_drain_pct:.0f}%" if self._finalize_drain_pct is not None else "--"
            text = f"Finalizacja: klatki {drain_txt}   |   {time_txt}   |   {size_txt}"
        else:
            stage_name = self._finalize_stage or "Finalizacja: zapis MP4"
            text = f"{stage_name}   |   {time_txt}   |   {size_txt}   |   {speed_txt}"

        self.lbl_stats.setText(text)

    def _on_render_phase(self, hud_state: dict, elapsed: float) -> None:
        """Raport fazy eksportu (prep/finalize) — mapowany na wspólny pasek."""
        phase = hud_state.get("phase", "")
        pct = max(0.0, min(1.0, float(hud_state.get("pct", 0.0) or 0.0)))
        label = str(hud_state.get("label", "") or "Renderowanie...")
        if phase == "prep":
            if "global_pct" in hud_state:
                overall = float(hud_state.get("global_pct"))
            else:
                overall = self._HUD_PREP_START + pct * (self._HUD_PREP_END - self._HUD_PREP_START)
            work_done = int(hud_state.get("work_done", 0))
            work_total = int(hud_state.get("work_total", 0))
            item_label = "HUD"
            completed = work_done
            total = work_total
        elif phase == "finalize":
            if "global_pct" in hud_state:
                overall = float(hud_state.get("global_pct"))
            else:
                overall = self._FINALIZE_START + pct * (self._FINALIZE_END - self._FINALIZE_START)
            item_label = "Frame"
            completed = 0
            total = 0
        else:
            return
        if overall > self._render_target:
            self._render_target = overall
        self._set_stats(completed, total, elapsed, 0.0, label, item_label=item_label)

    def _render_tick(self) -> None:
        """Płynna animacja wspólnego paska postępu eksportu (30 ms) oraz timer finalizacji."""
        if not self._rendering:
            self._render_timer.stop()
            return
        delta = self._render_target - self._render_display
        if delta <= 0.2:
            self._render_display = self._render_target
        else:
            self._render_display += max(delta * 0.2, 0.25)
            if self._render_display > self._render_target:
                self._render_display = self._render_target
        if not getattr(self, "_is_indeterminate", False):
            self.progress.setValue(int(round(self._render_display)))

        # Niezależny timer finalizacji co 1 s w GUI
        if self._in_finalize and self._finalize_start_mono is not None:
            sec = int(time.monotonic() - self._finalize_start_mono)
            if sec != self._last_finalize_tick_sec:
                self._last_finalize_tick_sec = sec
                self._update_finalize_status_label()

    def _set_stats(self, completed: int, total: int, elapsed: float, fps: float,
                   status: str, final_eta: str | None = None,
                   item_label: str = "Frame", is_indeterminate: bool = False,
                   qp: float | None = None, global_pct: float | None = None) -> None:
        total = max(total, 0)
        if not is_indeterminate and total and completed >= 0:
            if global_pct is not None and global_pct > 0:
                pct = global_pct
            else:
                pct = (completed / total) * 100.0
            frame_txt = f"{completed} / {total}"
            pct_txt = f"{pct:.1f}%"
        elif is_indeterminate and total:
            frame_txt = f"{completed} / {total}"
            pct_txt = "--"
        else:
            frame_txt = "--"
            pct_txt = "--"
        if final_eta is not None and not is_indeterminate:
            eta_txt = final_eta
        elif not is_indeterminate and fps > 0.05 and total and 0 <= completed < total:
            eta = (total - completed) / fps
            eta_txt = self._fmt_time(eta) if eta <= 360000 else "--:--"
        else:
            eta_txt = "--:--"
        elapsed_txt = self._fmt_time(elapsed) if (elapsed is not None and 0 < elapsed <= 3600000) else "--:--"
        fps_txt = f"{fps:.1f}" if (fps > 0.05 and not is_indeterminate) else "--"
        qp_str = f"{qp:.1f}" if (qp is not None and qp > 0 and not is_indeterminate) else "--"
        # Jedna linia — bez newline, bez łamania; stała wysokość labela
        # (Fixed + wordWrap=False) → brak przeskakiwania layoutu.
        self.lbl_stats.setText(
            f"{item_label}: {frame_txt}   |   {pct_txt}   |   FPS: {fps_txt}"
            f"   |   QP: {qp_str}   |   Czas: {elapsed_txt}   |   ETA: {eta_txt}"
            f"   |   {status}"
        )

    def _on_finished(self, _stats: dict, output: str) -> None:
        if self._render_state_enabled:
            return

        is_queue_job = bool(
            getattr(self, "_active_queue_job_id", None)
            or getattr(self, "_current_render_queue_job_id", None)
            or (_stats and _stats.get("_queue_job_id"))
        )
        q_job_id = (
            getattr(self, "_active_queue_job_id", None)
            or getattr(self, "_current_render_queue_job_id", None)
            or (_stats.get("_queue_job_id") if _stats else None)
        )

        elapsed = time.monotonic() - self._render_start if self._render_start else 0.0
        avg_fps = (
            _stats.get("real_export_fps")
            or _stats.get("true_fps")
            or _stats.get("render_fps")
            or (self._render_total / elapsed if elapsed > 0 and self._render_total else 0.0)
        ) if _stats else (self._render_total / elapsed if elapsed > 0 and self._render_total else 0.0)

        qp = None
        if _stats:
            qp = _stats.get("avg_qp", None)
            if qp is None and "encoder_stats" in _stats:
                qp = _stats.get("encoder_stats", {}).get("qp_avg")
            if qp is None and "amf_stats" in _stats:
                qp = _stats.get("amf_stats", {}).get("avg_qp")

        if is_queue_job:
            # QUEUE JOB: ZERO POPUPS! Record isolated stats directly to the queue job.
            if q_job_id and self._export_queue:
                self._export_queue.notify_render_done(
                    q_job_id,
                    success=True,
                    output_path=output,
                    elapsed_s=elapsed,
                    average_fps=avg_fps,
                    average_qp=qp,
                )
            self._current_render_queue_job_id = None
            if not self._rendering:
                return
            self._end_render()
            return

        # DIRECT / SINGLE EXPORT:
        self._current_render_queue_job_id = None
        if not self._rendering:
            if self._render_state is not None and self._render_state.completed:
                self._show_export_finished_popup(_stats, output, elapsed)
            return
        # Koniec — dopiero teraz 100% i status "Gotowe"
        self._is_indeterminate = False
        self.progress.setRange(0, 100)
        self._render_target = 100.0
        self._render_display = 100.0
        self._render_timer.stop()
        self.progress.setValue(100)
        self._set_stats(self._render_total, self._render_total, elapsed, avg_fps,
                        "Gotowe", final_eta="00:00", qp=qp)
        self._end_render()
        self._show_export_finished_popup(_stats, output, elapsed)

    def _show_export_finished_popup(self, stats: dict, output: str, elapsed: float = 0.0) -> None:
        time_str = self._fmt_time(elapsed) if elapsed > 0 else "--:--"
        
        avg_fps = (
            stats.get("real_export_fps")
            or stats.get("true_fps")
            or stats.get("render_fps")
            or (self._render_total / elapsed if elapsed > 0 and self._render_total else 0.0)
        )
        fps_str = f"{avg_fps:.1f} FPS" if (avg_fps and avg_fps > 0) else "brak danych"
        
        qp = stats.get("avg_qp", None)
        if qp is None and "encoder_stats" in stats:
            qp = stats.get("encoder_stats", {}).get("qp_avg")
        if qp is None and "amf_stats" in stats:
            qp = stats.get("amf_stats", {}).get("avg_qp")
            
        qp_str = f"{qp:.1f}" if qp is not None else "brak danych"
        self._last_export_fps = avg_fps
        self._last_export_qp = qp
        
        msg = (
            f"Plik zapisany:\n{output}\n\n"
            f"Czas eksportu: {time_str}\n"
            f"Średnia wydajność: {fps_str}\n"
            f"Średnie QP: {qp_str}"
        )
        QMessageBox.information(self, "Eksport zakończony", msg)

    def _on_error(self, msg: str) -> None:
        self._current_render_queue_job_id = None
        if self._render_state_enabled:
            return
        if not self._rendering:
            # Note: MainWindow._on_error odpowiada centralnie za prezentacje
            # okna dialogowego bledu. Brak duplikacji z poziomu RenderTab.
            return
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
        active_q_job = getattr(self, "_active_queue_job_id", None)
        self._active_queue_job_id = None
        if active_q_job and self._export_queue:
            is_success = bool(self._render_state and self._render_state.completed and not self._render_state.failed)
            elapsed = (
                self._render_state.elapsed_s
                if (self._render_state and getattr(self._render_state, "elapsed_s", 0.0) > 0)
                else (time.monotonic() - self._render_start if self._render_start else 0.0)
            )
            fps = getattr(self._render_state, "fps", 0.0) if self._render_state else 0.0
            self._export_queue.notify_render_done(
                active_q_job,
                success=is_success,
                cancelled=bool(self._render_state and self._render_state.cancelled) or self._cancelling,
                output_path=str(getattr(self._render_state, "output", "") or ""),
                elapsed_s=elapsed,
                average_fps=fps,
            )
        self._stop_export_preview("render_end")
        self._log_export_preview_resources()
        self._render_state_enabled = False
        self._in_finalize = False
        self._finalize_start_mono = None
        self._last_finalize_tick_sec = -1
        self._render_timer.stop()
        self._render_target = 0.0
        self._render_display = 0.0
        self.btn_render.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._is_indeterminate = False
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.hud_preview_label.clear()
        # Wróć do podglądu wideo (IN/OUT)
        self.hud_preview_label.setVisible(False)
        self.preview_slot.setVisible(True)
        self._update_preview_size()
        self._hud_ts = None
        self._last_preview_time = 0.0
        with self._preview_lock:
            self._preview_pending_ts = None
            self._preview_request_seq += 1
            self._gpu_tap_pending_payload = None
            self._gpu_tap_signal_pending = False
        self._export_preview_native = False
        self._export_preview_hevc = False
        self._export_preview_gpu_tap = False
        self._amd_export_preview_session = None
        self._export_preview_lightweight = False
        hud = getattr(self.video_preview, "hud_overlay", None)
        if hud is not None:
            hud.set_hud_pixmap(None)
            hud.hide()
        # Repaint the ordinary idle preview/HUD at its existing position;
        # this does not reload or decode another video stream.
        ctrl = self._controller
        if ctrl is not None and hasattr(ctrl, "_render_preview"):
            try:
                ctrl._render_preview(getattr(self.video_preview, "last_preview_ts", 0.0))
            except TypeError:
                try:
                    ctrl._render_preview()
                except Exception:
                    pass
            except Exception:
                pass

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
        self._hud_prepare_cache = build_activity_range_cache(
            getattr(ctrl, "layout", {}) or {},
            speed_samples=telemetry.speed_samples,
            track_samples=telemetry.track_samples,
            alt_samples=telemetry.alt_samples,
            gpx_speed_samples=telemetry.gpx_speed_samples,
            gpx_track_samples=telemetry.gpx_track_samples,
            gpx_alt_samples=telemetry.gpx_alt_samples,
            fit_data=telemetry.fit_data,
        )

    def _on_amd_hevc_preview_frame(self, raw: bytes, width: int, height: int) -> None:
        """Forward one latest-only FFmpeg BGRA frame to the GUI thread."""
        if not self._rendering or self._cancelling or not self._export_preview_hevc:
            return
        # Use the Preview generation, not the render cancel generation.  The
        # sidecar is intentionally independent from render cancellation and
        # stale callbacks must be rejected after a new Preview generation.
        with self._preview_lock:
            generation = self._preview_generation_id
        try:
            self.signals.sig_export_preview_ready.emit(
                (generation, "hevc", bytes(raw), int(width), int(height))
            )
        except Exception as exc:
            self._record_export_preview_error(
                generation=generation, timestamp=0.0,
                stage="frame_signal", exc=exc,
                worker=threading.current_thread().name,
                stop_event=self._preview_stop_event,
            )

    def _on_amd_hevc_preview_error(self, message: str) -> None:
        if not self._rendering or not self._export_preview_hevc:
            return
        with self._preview_lock:
            generation = self._preview_generation_id
        self.signals.sig_export_preview_ready.emit((generation, "error", str(message)))

    def _on_amd_gpu_preview_frame(self, raw: bytes, width: int, height: int) -> None:
        """Publish one latest-only native GPU tap frame to the GUI thread."""
        if not self._rendering or self._cancelling or not self._export_preview_gpu_tap:
            return
        with self._preview_lock:
            generation = self._preview_generation_id
            self._gpu_tap_pending_payload = (
                generation, "gpu_tap", bytes(raw), int(width), int(height)
            )
            if self._gpu_tap_signal_pending:
                return
            self._gpu_tap_signal_pending = True
        try:
            self.signals.sig_export_preview_ready.emit((generation, "gpu_tap_latest"))
        except Exception as exc:
            self._record_export_preview_error(
                generation=generation, timestamp=0.0,
                stage="gpu_tap_signal", exc=exc,
                worker=threading.current_thread().name,
                stop_event=self._preview_stop_event,
            )

    def _on_amd_gpu_preview_error(self, message: str) -> None:
        if not self._rendering or not self._export_preview_gpu_tap:
            return
        with self._preview_lock:
            generation = self._preview_generation_id
        self.signals.sig_export_preview_ready.emit((generation, "error", str(message)))

    def _on_export_preview_ready(self, payload) -> None:
        """Odbiera wyrenderowaną klatkę podglądu w głównym wątku GUI."""
        if isinstance(payload, tuple) and len(payload) == 2 and payload[1] == "gpu_tap_latest":
            with self._preview_lock:
                latest = self._gpu_tap_pending_payload
                self._gpu_tap_pending_payload = None
            if latest is None:
                with self._preview_lock:
                    self._gpu_tap_signal_pending = False
                return
            self._on_export_preview_ready(latest)
            with self._preview_lock:
                newer = self._gpu_tap_pending_payload
                if newer is None:
                    self._gpu_tap_signal_pending = False
            if newer is not None:
                try:
                    self.signals.sig_export_preview_ready.emit(
                        (int(newer[0]), "gpu_tap_latest")
                    )
                except Exception:
                    with self._preview_lock:
                        self._gpu_tap_signal_pending = False
            return
        worker_generation = self._preview_generation_id
        qimg = payload
        continuous_hevc = False
        gpu_tap = False
        if isinstance(payload, tuple) and len(payload) == 5 and payload[1] in ("hevc", "gpu_tap"):
            worker_generation, _kind, raw, raw_w, raw_h = payload
            gpu_tap = _kind == "gpu_tap"
            try:
                qimg = QImage(
                    raw, int(raw_w), int(raw_h), int(raw_w) * 4,
                    QImage.Format_ARGB32,
                ).copy()
                continuous_hevc = True
            except Exception as exc:
                self._record_export_preview_error(
                    generation=int(worker_generation), timestamp=0.0,
                    stage="qimage", exc=exc,
                    worker=threading.current_thread().name,
                    stop_event=self._preview_stop_event,
                )
                return
        if isinstance(payload, tuple) and len(payload) == 3 and payload[1] == "error":
            worker_generation, _kind, message = payload
            if worker_generation == self._preview_generation_id and self._rendering:
                self.hud_preview_label.setText("Preview unavailable")
            return
        if isinstance(payload, tuple) and len(payload) == 2:
            worker_generation, qimg = payload
        if worker_generation != self._preview_generation_id:
            return
        if not self._rendering or self._cancelling or qimg is None:
            return
        pix = QPixmap.fromImage(qimg)
        if continuous_hevc or gpu_tap:
            if gpu_tap:
                # Export dimming is a GUI-only affordance.  It is applied after
                # the tap readback and therefore cannot alter the MP4.
                qimg = dim_export_preview_qimage(
                    qimg,
                    render_active=self._rendering,
                )
                pix = QPixmap.fromImage(qimg)
            self.hud_preview_label.setPixmap(
                pix.scaled(self.hud_preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._log_export_preview_once(
                source="final_d3d11_frame",
                has_video_frame=True,
                has_hud=True,
                frame_size=f"{qimg.width()}x{qimg.height()}",
                preview_update_path="gpu_frame_tap" if gpu_tap else "continuous_ffmpeg_hevc",
            )
            return
        if self._export_preview_native:
            dpr = self.video_preview.get_dpr()
            if abs(pix.devicePixelRatio() - dpr) > 1e-4:
                pix.setDevicePixelRatio(dpr)
            hud = getattr(self.video_preview, "hud_overlay", None)
            if hud is not None:
                hud.set_hud_pixmap(pix)
                hud.sync_geometry()
                hud.show()
                hud.raise_()
            self._log_export_preview_once(
                source="native_video_widget",
                has_video_frame=True,
                has_hud=True,
                frame_size=f"{qimg.width()}x{qimg.height()}",
                preview_update_path="native_hud_overlay",
            )
            return
        self.hud_preview_label.setPixmap(
            pix.scaled(self.hud_preview_label.size(),
                       Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self._log_export_preview_once(
            source="last_src_pil",
            has_video_frame=True,
            has_hud=True,
            frame_size=f"{qimg.width()}x{qimg.height()}",
            preview_update_path="pil_composite",
        )

    def _uses_native_export_video(self) -> bool:
        """Whether idle preview paints video outside the PIL image path."""
        ctrl = self._controller
        return bool(
            self.video_preview.is_using_mpv()
            or getattr(ctrl, "_preview_mode", "hud") == "gpu_video"
        )

    def _log_export_preview_once(
        self, *, source: str, has_video_frame: bool, has_hud: bool,
        frame_size: str, preview_update_path: str,
    ) -> None:
        if self._export_preview_logged:
            return
        with self._export_preview_log_lock:
            if self._export_preview_logged:
                return
            self._export_preview_logged = True
            print(
                "[ExportPreview] "
                f"source={source} has_video_frame={int(has_video_frame)} "
                f"has_hud={int(has_hud)} frame_size={frame_size} "
                f"preview_update_path={preview_update_path}",
                flush=True,
            )

    def _sync_export_video_to_timestamp(self, global_ts: float) -> None:
        """Move the visible source video to the exporter HUD timestamp."""
        if self._controller is None:
            return
        ctrl = self._controller
        if (
            not self._export_preview_native
            and getattr(ctrl, "media_player", None) is None
        ):
            return
        try:
            global_ts = max(0.0, float(global_ts))
            resolve_time = getattr(ctrl, "_resolve_preview_time", None)
            if not callable(resolve_time):
                return
            resolved = resolve_time(global_ts)
            local_ts = float(resolved.get("local_time", global_ts))
            clip_index = resolved.get("clip_index")
            clip = resolved.get("clip")
            old_clip_index = getattr(ctrl, "_active_preview_clip_index", None)

            mpv = getattr(ctrl, "mpv_player", None)
            mpv_path_before = (
                getattr(mpv, "path", None) or getattr(mpv, "filename", None)
            ) if mpv is not None else None

            ensure_clip = getattr(ctrl, "_preview_ensure_active_clip", None)
            switched = bool(
                callable(ensure_clip)
                and ensure_clip(clip_index, clip, local_ts, global_ts)
            )

            if mpv is not None:
                if switched:
                    self._pending_hud_switch_log = True
                    file_loaded_ok = False
                    # Bounded event-driven wait for MPV to finish loading the new clip
                    if hasattr(mpv, "wait_for_event"):
                        try:
                            file_loaded_ok = bool(mpv.wait_for_event("file-loaded", timeout=0.5))
                        except Exception:
                            file_loaded_ok = False
                    if not file_loaded_ok and hasattr(mpv, "wait_for_property"):
                        try:
                            file_loaded_ok = bool(mpv.wait_for_property("seekable", lambda v: v is True, timeout=0.3))
                        except Exception:
                            pass

                    mpv_path_after = getattr(mpv, "path", None) or getattr(mpv, "filename", None)
                    dur = getattr(mpv, "duration", None)
                    seek_result = "PENDING"
                    try:
                        mpv.seek(local_ts, reference="absolute")
                        mpv.pause = True
                        ctrl._source_transition_in_progress = False
                        seek_result = "OK"
                    except Exception as e:
                        seek_result = f"FAILED ({e})"
                        ctrl._mpv_pending_seek_s = local_ts

                    time_pos = getattr(mpv, "time_pos", None)
                    clip_path_str = str(getattr(clip, "path", "?"))
                    file_loaded_str = "YES" if file_loaded_ok else "NO"

                    print(
                        f"[MultiFile Export Preview Switch]\n"
                        f"  requested global timestamp: {global_ts:.3f}\n"
                        f"  old clip index: {old_clip_index}\n"
                        f"  new clip index: {clip_index}\n"
                        f"  new file path: {clip_path_str}\n"
                        f"  requested local timestamp: {local_ts:.3f}\n"
                        f"  mpv path before load: {mpv_path_before}\n"
                        f"  loadfile issued: YES\n"
                        f"  file-loaded received: {file_loaded_str}\n"
                        f"  mpv path after load: {mpv_path_after}\n"
                        f"  duration: {dur}\n"
                        f"  seek issued: {local_ts:.3f}\n"
                        f"  seek result: {seek_result}\n"
                        f"  time-pos: {time_pos}",
                        flush=True,
                    )
                    return
                else:
                    try:
                        if getattr(ctrl, "_source_transition_in_progress", False):
                            if getattr(mpv, "seekable", False):
                                mpv.seek(local_ts, reference="absolute")
                                mpv.pause = True
                                ctrl._source_transition_in_progress = False
                        else:
                            mpv.seek(local_ts, reference="absolute")
                            mpv.pause = True
                    except Exception as e:
                        # Transient seek warning - do not kill preview generation!
                        print(f"[Export Preview] Transient MPV seek warning at global_ts={global_ts:.3f}, local_ts={local_ts:.3f}: {e}", flush=True)
                    return

            media_player = getattr(ctrl, "media_player", None)
            if media_player is not None:
                try:
                    media_player.setPosition(max(0, int(round(local_ts * 1000.0))))
                    # QVideoSink needs the player running to deliver a new frame;
                    # _on_video_frame pauses it again after the pending seek.
                    if not getattr(ctrl, "_playing", False):
                        ctrl._seek_pending = True
                        media_player.play()
                except Exception as exc:
                    print(f"[Export Preview] QMedia seek warning: {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[Export Preview] Warning in video sync at global_ts={global_ts:.3f}: {exc}", flush=True)

    def _preview_is_foreground(self) -> bool:
        """Preview is an optional foreground consumer, never a render dependency."""
        try:
            window = self.window()
            return bool(
                window is not None
                and window.isVisible()
                and not window.isMinimized()
                and window.isActiveWindow()
            )
        except Exception:
            return False

    def export_preview_diagnostics(self) -> dict[str, object]:
        """Read-only Export Preview state; it never controls final export."""
        with self._preview_lock:
            pending = self._preview_pending_ts
            active = self._preview_worker_active
            seq = self._preview_request_seq
            timings = list(self._preview_update_times_ms)
        hevc_stats = (
            self._amd_export_preview_session.stats()
            if self._amd_export_preview_session is not None
            else dict(self._last_continuous_hevc_stats)
        )
        ctrl = self._controller
        render_holder = getattr(ctrl, "render_process_holder", {}) if ctrl is not None else {}
        child_process = render_holder.get("process") if isinstance(render_holder, dict) else None
        try:
            window = self.window()
        except Exception:
            window = None
        return {
            "enabled": bool(self.chk_hud_preview.isChecked()),
            "worker_active": active,
            "pending_latest": pending is not None,
            "pending_timestamp": pending,
            "request_sequence": seq,
            "preview_generation_id": self._preview_generation_id,
            "worker_thread_alive": bool(
                self._preview_worker_thread is not None
                and self._preview_worker_thread.is_alive()
            ),
            "active_decoders": self._preview_decode_active,
            "last_timestamp": self._hud_ts,
            "failed": self._preview_failed,
            "decoder": self._preview_decoder,
            "updates": len(timings),
            "mean_ms": (sum(timings) / len(timings)) if timings else 0.0,
            "foreground": self._preview_is_foreground(),
            "visible": bool(window is not None and window.isVisible()),
            "minimized": bool(window is not None and window.isMinimized()),
            "continuous_hevc": hevc_stats,
            "render_child": {
                "pid": getattr(child_process, "pid", render_holder.get("child_pid") if isinstance(render_holder, dict) else None),
                "alive": bool(child_process is not None and child_process.poll() is None),
                "generation_id": render_holder.get("child_generation_id") if isinstance(render_holder, dict) else None,
            },
        }

    def notify_window_state_changed(self) -> None:
        """Resume exactly one newest preview request after foreground return."""
        if self._rendering and not self._cancelling and self.chk_hud_preview.isChecked():
            if self._preview_is_foreground() and self._hud_ts is not None:
                self._trigger_async_preview(self._hud_ts)

    def _trigger_async_preview(self, ts: float) -> None:
        """Uruchamia asynchroniczny render klatki podglądu w tle (zero backpressure)."""
        if self._export_preview_hevc:
            return
        if (
            not self._rendering or self._cancelling or self._controller is None
            or self._preview_stop_event.is_set() or self._preview_failed
        ):
            return

        # Qt widgets and video players stay on the GUI thread.  AMD's
        # lightweight mode deliberately does not seek MPV/QMedia at all.
        if self._export_preview_native:
            self._sync_export_video_to_timestamp(ts)
            if self._preview_failed:
                return
            phys = self.video_preview.get_physical_video_rect()
            tw = phys.width() if phys.width() > 10 else 640
            th = phys.height() if phys.height() > 10 else 360
        else:
            available_w = self.hud_preview_label.width()
            tw = min(480, available_w) if available_w > 100 else 480
            layout = getattr(self._controller, "layout", None) or {}
            lw = int(layout.get("width", 1920) or 1920)
            lh = int(layout.get("height", 1080) or 1080)
            th = max(1, int(tw * lh / lw)) if lw > 0 else int(tw * 9 / 16)
        with self._preview_lock:
            self._preview_pending_ts = float(ts)
            self._preview_request_seq += 1
            if self._preview_worker_active or not self._preview_is_foreground():
                return
            self._preview_worker_active = True
            self._preview_busy = True
            self._preview_worker_starts += 1
            first_worker = self._preview_worker_starts == 1

        worker_stop_event = self._preview_stop_event
        worker_generation = self._render_generation_id

        def worker():
            if first_worker:
                self._log_preview_resource_snapshot("B_during_preview_on")
            try:
                while not worker_stop_event.is_set():
                    with self._preview_lock:
                        next_ts = self._preview_pending_ts
                        seq = self._preview_request_seq
                        self._preview_pending_ts = None
                    if next_ts is None:
                        break
                    if (
                        os.environ.get("TELEM_EXPORT_PREVIEW_FAULT_INJECTION", "0") == "1"
                        and not self._preview_fault_injected
                    ):
                        self._preview_fault_injected = True
                        raise RuntimeError("preview fault injection")
                    started = time.perf_counter()
                    qimg = self._build_preview_qimage(next_ts, tw, th)
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    with self._preview_lock:
                        self._preview_update_times_ms.append(elapsed_ms)
                        still_latest = seq == self._preview_request_seq
                        if still_latest and qimg is not None:
                            self._preview_emitted_seq = seq
                    if qimg is not None and still_latest and not worker_stop_event.is_set():
                        # Carry the generation through the queued Qt signal;
                        # a result queued before Preview OFF/new render must
                        # never paint the next generation.
                        self.signals.sig_export_preview_ready.emit(
                            (worker_generation, qimg)
                        )
            except BaseException as exc:  # Preview failure must never escape.
                self._record_export_preview_error(
                    generation=worker_generation,
                    timestamp=float(next_ts if "next_ts" in locals() and next_ts is not None else ts),
                    stage="preview_worker", exc=exc,
                    worker=threading.current_thread().name,
                    stop_event=worker_stop_event,
                )
            finally:
                with self._preview_lock:
                    if worker_stop_event is self._preview_stop_event:
                        self._preview_worker_active = False
                        self._preview_busy = False
                        if self._preview_worker_thread is threading.current_thread():
                            self._preview_worker_thread = None

        preview_thread = threading.Thread(
            target=worker, daemon=True,
            name=f"TeleM-ExportPreview-{worker_generation}",
        )
        with self._preview_lock:
            self._preview_worker_thread = preview_thread
        preview_thread.start()

    def _record_export_preview_error(
        self, *, generation: int, timestamp: float, stage: str,
        exc: BaseException, worker: str, stop_event: threading.Event,
    ) -> None:
        """Disable only this Preview generation and print its full traceback."""
        with self._preview_lock:
            if (
                stop_event is not self._preview_stop_event
                or generation != self._render_generation_id
            ):
                stop_event.set()
                return
            self._preview_failed = True
            self._preview_pending_ts = None
        stop_event.set()
        self._log_preview_resource_snapshot("C_after_preview_error")
        trace = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).rstrip()
        print("[EXPORT PREVIEW ERROR]", flush=True)
        print(f"generation={generation}", flush=True)
        print(f"preview_generation={self._preview_generation_id}", flush=True)
        print(f"timestamp={timestamp:.6f}", flush=True)
        print(f"worker={worker}", flush=True)
        print(f"stage={stage}", flush=True)
        print(f"exception_type={type(exc).__name__}", flush=True)
        print(f"exception={exc}", flush=True)
        print(f"traceback={trace}", flush=True)

    def _log_export_preview_resources(self) -> None:
        if self._preview_resources_reported:
            return
        with self._preview_lock:
            timings = sorted(self._preview_update_times_ms)
            workers = self._preview_worker_starts
        mean_ms = sum(timings) / len(timings) if timings else 0.0
        if timings:
            p95_index = min(
                len(timings) - 1,
                max(0, int(round(0.95 * (len(timings) - 1)))),
            )
            p95_ms = timings[p95_index]
        else:
            p95_ms = 0.0
        self._preview_resources_reported = True
        hevc_stats = (
            self._amd_export_preview_session.stats()
            if self._amd_export_preview_session is not None else {}
        )
        if hevc_stats:
            self._last_continuous_hevc_stats = dict(hevc_stats)
        print("[EXPORT PREVIEW RESOURCES]", flush=True)
        print(f"decoder={self._preview_decoder}", flush=True)
        print(f"hardware_decode={self._preview_hardware_decode}", flush=True)
        print(f"device={self._preview_device}", flush=True)
        print(f"workers={min(1, workers)}", flush=True)
        print(f"updates={hevc_stats.get('updates', len(timings))}", flush=True)
        print(f"mean_ms={mean_ms:.3f}", flush=True)
        print(f"p95_ms={p95_ms:.3f}", flush=True)
        if hevc_stats:
            print(f"backend={hevc_stats.get('backend', self._preview_decoder)}", flush=True)
            print(f"preview_process_alive={int(bool(hevc_stats.get('alive')))}", flush=True)
            print(f"dropped={hevc_stats.get('dropped', hevc_stats.get('dropped_chunks', 0))}", flush=True)
            print(f"capture_inflight={hevc_stats.get('capture_inflight', 0)}", flush=True)
            print(f"avg_capture_ms={float(hevc_stats.get('avg_capture_ms', 0.0) or 0.0):.3f}", flush=True)
            print(f"max_capture_ms={float(hevc_stats.get('max_capture_ms', 0.0) or 0.0):.3f}", flush=True)
            print(f"gui_pending={hevc_stats.get('gui_pending', 0)}", flush=True)
            print(f"restarts={hevc_stats.get('restarts', 0)}", flush=True)
            print(f"last_error={hevc_stats.get('last_error', '')}", flush=True)

    def _build_preview_qimage(self, ts: float, tw: int, th: int) -> QImage | None:
        """Renderuje klatkę wideo + HUD overlay do QImage (background thread)."""
        try:
            from src.overlay_renderer import prepare_overlay_frame_data, build_chart_data, compose_overlay
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
                act_mapper_tmp = getattr(getattr(telemetry, "fit_data", None), "active_time_mapper", None)
                self._hud_chart_data = build_chart_data(
                    layout, telemetry.get_samples_for_source, telemetry.resolve_samples,
                    start_dt_utc=telemetry.start_dt_utc, end_dt_utc=end_dt_tmp,
                    source_activity_ranges=source_ranges_tmp,
                    active_time_mapper=act_mapper_tmp,
                )
            if self._hud_prepare_cache is None:
                self._build_hud_prepare_cache()

            # Wczytaj klatkę wideo odpowiadającą aktualnemu czasowi eksportu
            base = None
            if not self._export_preview_native:
                last_src = (
                    self._preview_cached_video_frame
                    if self._export_preview_lightweight else None
                )
                if last_src is None:
                    last_src = getattr(ctrl, "last_src_pil", None)
                if last_src is None:
                    last_src = getattr(ctrl, "src_img", None)
                # Without an active native/QMedia decoder, the cached image
                # may be the first idle frame. Decode the requested exporter
                # timestamp instead of silently compositing HUD over it.
                try:
                    should_decode = (
                        not self._export_preview_lightweight
                        or self._preview_cached_video_frame is None
                        or self._preview_last_video_decode_ts is None
                        or abs(float(ts) - self._preview_last_video_decode_ts) >= 8.0
                    )
                    if (
                        should_decode
                        and (self._export_preview_lightweight or getattr(ctrl, "media_player", None) is None)
                    ):
                        from src.video_helpers import extract_frame
                        v_paths = getattr(ctrl, "video_paths", None) or [getattr(ctrl, "video_path", None)]
                        with self._preview_lock:
                            self._preview_decode_active += 1
                        try:
                            decoded = extract_frame(
                                v_paths,
                                ts,
                                ffmpeg_exe=getattr(ctrl, "ffmpeg_exe", "ffmpeg") or "ffmpeg",
                                ffprobe_exe=getattr(ctrl, "ffprobe_exe", "ffprobe") or "ffprobe",
                                target_w=tw,
                                preferred_encoder="cpu",
                                cache_capture=False,
                            )
                        finally:
                            with self._preview_lock:
                                self._preview_decode_active = max(0, self._preview_decode_active - 1)
                        if decoded is not None:
                            last_src = decoded
                            if self._export_preview_lightweight:
                                self._preview_cached_video_frame = decoded.copy()
                                self._preview_last_video_decode_ts = float(ts)
                    if isinstance(last_src, Image.Image) and last_src.width > 1 and last_src.height > 1:
                        snapshot = last_src.copy()
                        if snapshot.mode == "RGBA" and snapshot.getchannel("A").getextrema() == (0, 0):
                            snapshot = None
                        if snapshot is not None:
                            base = snapshot.convert("RGBA").resize(
                                (tw, th), Image.Resampling.BILINEAR
                            )
                except Exception:
                    base = None
            if not self._export_preview_native and base is None:
                self._log_export_preview_once(
                    source="none",
                    has_video_frame=False,
                    has_hud=False,
                    frame_size=f"{tw}x{th}",
                    preview_update_path="no_video_snapshot",
                )
                return None

            start_dt = telemetry.start_dt_utc
            # ETAP 4A: prefer the project timeline for GLOBAL -> ABSOLUTE mapping
            # (multi-file); fall back to the legacy single-start formula.
            timeline = getattr(ctrl, "video_timeline", None)
            target_dt = None
            if timeline is not None and timeline.clip_count:
                target_dt = timeline.global_to_absolute(
                    ts, base_dt=start_dt
                )
            if target_dt is None:
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
                gps_track=(
                    telemetry.resolve_gps_track(
                        layout.get("indicators", {}).get("track_map", {}).get("gps_source", "auto")
                    )[0]
                    if hasattr(telemetry, "resolve_gps_track")
                    else telemetry.get_gps_track_for_source(
                        layout.get("indicators", {}).get("track_map", {}).get("gps_source", "auto")
                    )
                ),
                total_frames=max(1, int(video_dur)),
                current_index=int(ts) if ts else 0,
                chart_data=self._hud_chart_data,
                extra_field_keys=getattr(ctrl, "fit_ext_fields", None),
                resolve_cache_value=lambda k, src, dt, indicator_key=None, **kwargs: telemetry.resolve_value(
                    k, dt, source=src, indicator_key=indicator_key, **kwargs
                ),
                _range_cache=self._hud_prepare_cache,
                project_elapsed_s=ts,
            )
            if not overlay_data:
                return None
            from src.ffmpeg.streaming import resolve_hud_resolution_policy
            hud_scale, _ = resolve_hud_resolution_policy(
                encoder=self._preview_encoder_text,
                render_w=tw,
                render_h=th,
                user_option=self._preview_hud_option,
            )
            hud_w = max(2, int(round(tw * hud_scale)))
            hud_h = max(2, int(round(th * hud_scale)))
            if hud_w % 2:
                hud_w += 1
            if hud_h % 2:
                hud_h += 1
            if self._export_preview_native:
                preview_base = Image.new("RGBA", (hud_w, hud_h), (0, 0, 0, 0))
            else:
                preview_base = base if hud_scale == 1.0 else base.resize(
                    (hud_w, hud_h), Image.Resampling.BILINEAR
                )
            overlay = compose_overlay(
                preview_base.width, preview_base.height,
                layout, getattr(ctrl, "font_path", None),
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
                auto_ranges=overlay_data.get("auto_ranges"),
                async_map=True,
                fast_preview=True,
            )
            preview = overlay if self._export_preview_native else compose_export_preview(
                preview_base, overlay,
            )
            rgba = preview.convert("RGBA")
            if hud_scale != 1.0:
                rgba = rgba.resize((tw, th), Image.Resampling.BILINEAR)
            data = rgba.tobytes("raw", "RGBA")
            qimg = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888).copy()
            if getattr(self, "_pending_hud_switch_log", False):
                self._pending_hud_switch_log = False
                print(
                    f"[MultiFile Export Preview Switch] HUD preview composition result: OK ({qimg.width()}x{qimg.height()})",
                    flush=True,
                )
            return qimg
        except Exception as exc:
            if getattr(self, "_pending_hud_switch_log", False):
                self._pending_hud_switch_log = False
                print(
                    f"[MultiFile Export Preview Switch] HUD preview composition result: FAILED ({exc})",
                    flush=True,
                )
            raise

    def _on_amd_decode_mode_restored(self, mode: str) -> None:
        """Przywraca zaznaczenie trybu dekodowania AMD w cmb_amd_decode."""
        mode_clean = (mode or "gpu").lower()
        self.cmb_amd_decode.blockSignals(True)
        idx = self.cmb_amd_decode.findData(mode_clean)
        if idx >= 0:
            self.cmb_amd_decode.setCurrentIndex(idx)
        else:
            self.cmb_amd_decode.setCurrentIndex(0)
            mode_clean = "gpu"
        self.lbl_cpu_warning.setVisible(mode_clean == "cpu")
        self.cmb_amd_decode.blockSignals(False)

    def set_amd_decode_mode(self, mode: str) -> None:
        """Publiczna metoda ustawiająca tryb dekodowania AMD w zakładce Renderowania."""
        self._on_amd_decode_mode_restored(mode)

    def _on_amd_encoder_quality_restored(self, quality: str) -> None:
        """Przywraca zaznaczenie presetu jakości AMD w cmb_amd_quality."""
        q_clean = (quality or "FAST").upper()
        self.cmb_amd_quality.blockSignals(True)
        idx = self.cmb_amd_quality.findData(q_clean)
        if idx >= 0:
            self.cmb_amd_quality.setCurrentIndex(idx)
        else:
            self.cmb_amd_quality.setCurrentIndex(0)
        self.cmb_amd_quality.blockSignals(False)

    def set_amd_encoder_quality(self, quality: str) -> None:
        """Publiczna metoda ustawiająca preset jakości AMD w zakładce Renderowania."""
        self._on_amd_encoder_quality_restored(quality)

    # ── Wymuszanie proporcji 16:9 i dopasowanie do ProjectTab ──────────

    def showEvent(self, event) -> None:
        """Po pokazaniu zakładki przelicz szerokość podglądu (16:9)."""
        super().showEvent(event)
        self._update_preview_width()

    def resizeEvent(self, event) -> None:
        """Przy każdej zmianie rozmiaru przelicz szerokość podglądu."""
        super().resizeEvent(event)
        self._update_preview_width()

    def _update_preview_width(self) -> None:
        """Ustaw wspólny rozmiar podglądu 16:9 — ten sam co w ProjectTab."""
        total_w = self.width()
        total_h = self.height()
        if total_w < 100 or total_h < 100:
            return

        preview_w, preview_h = preview_aspect_size(total_h, total_w)
        self.left_panel.setFixedWidth(preview_w + 4)
        self.preview_slot.setFixedSize(preview_w, preview_h)
        self.hud_preview_label.setFixedSize(preview_w, preview_h)


    def get_encoder_profile(self) -> EncoderProfile:
        """Return the currently selected EncoderProfile."""
        if hasattr(self, "cmb_encoder_profile") and self.cmb_encoder_profile:
            val = self.cmb_encoder_profile.currentData()
            if isinstance(val, EncoderProfile):
                return val
            if isinstance(val, str):
                return EncoderProfile.from_str(val)
            text = self.cmb_encoder_profile.currentText()
            return EncoderProfile.from_str(text)
        return EncoderProfile.BALANCED

    def apply_export_settings(self, settings: dict[str, Any]) -> None:
        """Apply export settings dict to UI widgets, honoring legacy defaults.
        
        If 'encoder_profile' is absent in settings (legacy project/preset),
        it defaults to LEGACY_DEFAULT_ENCODER_PROFILE (FAST, TU=7) to preserve
        exact historical Intel rendering behavior.
        """
        if "encoder_profile" in settings and hasattr(self, "cmb_encoder_profile"):
            prof = EncoderProfile.from_str(settings["encoder_profile"], default=DEFAULT_ENCODER_PROFILE)
            idx = self.cmb_encoder_profile.findData(prof.value)
            if idx >= 0:
                self.cmb_encoder_profile.setCurrentIndex(idx)
        elif hasattr(self, "cmb_encoder_profile"):
            idx = self.cmb_encoder_profile.findData(LEGACY_DEFAULT_ENCODER_PROFILE.value)
            if idx >= 0:
                self.cmb_encoder_profile.setCurrentIndex(idx)
