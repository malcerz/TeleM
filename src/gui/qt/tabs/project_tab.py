"""Zakładka Projekt — podgląd wideo + panel właściwości + przyciski danych.

Układ dynamiczny: podgląd w proporcji 16:9 (wysokość × 16/9),
panel właściwości wypełnia resztę szerokości.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy,
)

from src.gui.qt.signals import get_signals
from src.gui.qt.widgets.video_preview import VideoPreview
from src.gui.qt.widgets.data_stream_bar import DataStreamBar
from src.gui.qt.widgets.property_editor import PropertyEditor


class ProjectTab(QWidget):
    """Główna zakładka projektowa.

    Układ:
    - Poziomo: podgląd wideo (16:9) + panel właściwości (reszta)
    - Lewy pionowo: podgląd na górze, przyciski danych na dole
    - Brak lewego marginesu — podgląd przylega do lewej krawędzi
    """

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._build_ui()

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)

        # ── Główny poziom QHBoxLayout ───────────────────────────────────
        hlayout = QHBoxLayout()
        hlayout.setContentsMargins(0, 0, 0, 0)
        hlayout.setSpacing(0)

        # LEWY: podgląd wideo + dynamiczne przyciski
        self.left_panel = QWidget()
        self.left_panel.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Preferred,
        )
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 4, 4, 4)  # brak lewego marginesu

        self.video_preview = VideoPreview()
        left_layout.addWidget(self.video_preview, 8)  # 80% wysokości

        self.data_bar = DataStreamBar()
        left_layout.addWidget(self.data_bar, 2)        # 20% wysokości

        # PRAWY: panel właściwości (wypełnia resztę)
        self.property_editor = PropertyEditor()
        self.property_editor.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred,
        )

        hlayout.addWidget(self.left_panel)             # fixed 16:9 width
        hlayout.addWidget(self.property_editor, 1)     # stretch → fills rest

        vbox.addLayout(hlayout)

        # ── Podłącz sygnały z kontrolera do widgetów ───────────────────
        s = self.signals
        s.sig_preview_frame_ready.connect(self.video_preview.on_frame_ready)
        s.sig_bboxes_ready.connect(self.video_preview.set_bboxes)
        s.sig_data_streams_ready.connect(self.data_bar.on_streams_ready)
        s.sig_properties_ready.connect(self.property_editor.on_properties_ready)
        s.sig_video_duration_ready.connect(self.video_preview.on_duration_ready)

    # ── Wymuszanie proporcji 16:9 ──────────────────────────────────────

    def resizeEvent(self, event) -> None:
        """Przy każdej zmianie rozmiaru przelicz szerokość podglądu."""
        super().resizeEvent(event)
        self._update_preview_width()

    def _update_preview_width(self) -> None:
        """Ustaw szerokość lewego panelu tak, by podgląd miał proporcję 16:9.

        Podgląd zajmuje ~80% wysokości lewego panelu;
        jego szerokość = (80% wysokości) × 16/9.
        """
        total_w = self.width()
        total_h = self.height()
        if total_w < 100 or total_h < 100:
            return

        # Wysokość dostępna dla podglądu (~80% z total_h)
        preview_h = int(total_h * 0.8)
        # Szerokość w proporcji 16:9
        preview_w = int(preview_h * 16.0 / 9.0)

        # Zabezpieczenie: nie zajmuj całej szerokości, zostaw min 220px dla właściwości
        min_prop = 220
        preview_w = min(preview_w, total_w - min_prop)
        preview_w = max(preview_w, 300)

        self.left_panel.setFixedWidth(preview_w)
