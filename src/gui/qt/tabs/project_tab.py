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
from src.gui.qt.widgets.video_preview import VideoPreview, preview_aspect_size
from src.gui.qt.widgets.data_stream_bar import DataStreamBar
from src.gui.qt.widgets.property_editor import PropertyEditor


class ProjectTab(QWidget):
    """Główna zakładka projektowa.

    Układ:
    - Poziomo: podgląd wideo (16:9) + panel właściwości (reszta)
    - Lewy pionowo: podgląd na górze, przyciski danych na dole
    - Brak lewego marginesu — podgląd przylega do lewej krawędzi

    Podgląd wideo może być WSPÓŁDZIELONY z zakładką Rendering: gdy podano
    instancję ``preview``, zakładka używa jej zamiast tworzyć własną
    (współdzielony widget jest przenoszony między zakładkami przez MainWindow).
    """

    def __init__(self, preview: VideoPreview | None = None) -> None:
        super().__init__()
        self.signals = get_signals()
        self._owns_preview = preview is None
        self.video_preview = preview if preview is not None else VideoPreview()
        self._build_ui()
        if self._owns_preview:
            self._connect_preview_signals()

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

        # Kontener na (współdzielony) podgląd wideo
        self.preview_slot = QWidget()
        self.preview_slot.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding,
        )
        self.preview_slot_layout = QVBoxLayout(self.preview_slot)
        self.preview_slot_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_slot_layout.setSpacing(0)
        left_layout.addWidget(self.preview_slot, 0)  # stała wysokość (16:9)
        if self._owns_preview:
            self.preview_slot_layout.addWidget(self.video_preview)

        self.data_bar = DataStreamBar()
        left_layout.addWidget(self.data_bar, 1)        # wypełnia resztę wysokości

        # PRAWY: panel właściwości (wypełnia resztę)
        self.property_editor = PropertyEditor()
        self.property_editor.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred,
        )

        hlayout.addWidget(self.left_panel)             # fixed 16:9 width
        hlayout.addWidget(self.property_editor, 1)     # stretch → fills rest

        vbox.addLayout(hlayout)

        # ── Sygnały panelu właściwości / danych (niezależne od podglądu) ─
        s = self.signals
        s.sig_data_streams_ready.connect(self.data_bar.on_streams_ready)
        s.sig_properties_ready.connect(self.property_editor.on_properties_ready)

    def _connect_preview_signals(self) -> None:
        """Podłącz sygnały podglądu — tylko gdy zakładka posiada podgląd.

        W trybie współdzielonym sygnały podglądu podłącza MainWindow
        (dokładnie raz), aby uniknąć zdublowanych połączeń.
        """
        s = self.signals
        s.sig_preview_frame_ready.connect(self.video_preview.on_frame_ready)
        s.sig_bboxes_ready.connect(self.video_preview.set_bboxes)
        s.sig_video_duration_ready.connect(self.video_preview.on_duration_ready)
        s.sig_seek_position.connect(self.video_preview._on_seek_position)

    def set_controller(self, controller: object) -> None:
        """Ustaw referencję do kontrolera (wywoływane z application.py).

        Gdy podgląd jest współdzielony, backend wiąże MainWindow (raz);
        tutaj wiążemy tylko w trybie samodzielnego podglądu.
        """
        if self._owns_preview:
            self.video_preview.set_controller(controller)

    # ── Wymuszanie proporcji 16:9 ──────────────────────────────────────

    def showEvent(self, event) -> None:
        """Po pokazaniu zakładki przelicz szerokość podglądu (16:9)."""
        super().showEvent(event)
        self._update_preview_width()

    def resizeEvent(self, event) -> None:
        """Przy każdej zmianie rozmiaru przelicz szerokość podglądu."""
        super().resizeEvent(event)
        self._update_preview_width()

    def _update_preview_width(self) -> None:
        """Ustaw wspólny rozmiar podglądu 16:9 — ten sam co w Rendering.

        Wysokość = ~80% wysokości zakładki; szerokość w proporcji 16:9,
        ograniczona szerokością dostępną dla podglądu (tak, by ten sam
        rozmiar zmieścił się również w obszarze Rendering ~75%).
        """
        total_w = self.width()
        total_h = self.height()
        if total_w < 100 or total_h < 100:
            return

        preview_w, preview_h = preview_aspect_size(total_h, total_w)
        # left_panel ma prawy margines 4px — dodaj go do szerokości panelu
        self.left_panel.setFixedWidth(preview_w + 4)
        self.preview_slot.setFixedSize(preview_w, preview_h)
