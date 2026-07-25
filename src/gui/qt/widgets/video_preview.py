"""Widget podglądu wideo z osią czasu i interakcją myszką."""

from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSlider, QHBoxLayout, QPushButton,
)

from src.gui.qt.signals import get_signals


class VideoPreview(QWidget):
    """Podgląd wideo + suwak osi czasu + klikalne/przeciągalne wskaźniki.

    Odbiera QPixmap z kontrolera przez sygnał sig_preview_frame_ready.
    Odbiera bounding boxy przez set_bboxes().
    Emituje sig_indicator_clicked / sig_indicator_moved.
    """

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._duration_s = 100.0
        self._bboxes: dict[str, tuple[int, int, int, int]] = {}
        self._dragging_key: str | None = None
        self._pixmap_size: tuple[int, int] = (0, 0)
        self._pixmap_offset: tuple[int, int] = (0, 0)
        self._original_size: tuple[int, int] = (0, 0)
        self._build_ui()
        # Event filter na image_label do przechwytywania zdarzeń myszy
        self.image_label.installEventFilter(self)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Obraz podglądu
        self.image_label = QLabel("Wybierz plik wideo\nw zakładce Wczytywanie")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet(
            "background-color: #1a1a1a; color: #666;"
            "font-size: 14px; border: 1px solid #333;"
        )
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setScaledContents(False)
        self.image_label.setMouseTracking(True)
        layout.addWidget(self.image_label, 1)

        # Oś czasu + Play/Stop (ta sama linia)
        time_row = QHBoxLayout()
        time_row.setContentsMargins(4, 2, 4, 2)
        time_row.setSpacing(4)

        self.play_btn = QPushButton("\u25B6")
        self.play_btn.setFixedSize(28, 26)
        self.play_btn.setToolTip("Odtwarzaj")
        self.play_btn.setStyleSheet(
            "QPushButton { background-color: #2a6a2a; color: #88ff88; "
            "border: 1px solid #4a8a4a; border-radius: 3px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background-color: #3a8a3a; }"
        )
        self.play_btn.clicked.connect(lambda: self.signals.sig_playback_start.emit())
        time_row.addWidget(self.play_btn)

        self.stop_btn = QPushButton("\u25A0")
        self.stop_btn.setFixedSize(28, 26)
        self.stop_btn.setToolTip("Zatrzymaj")
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #6a2a2a; color: #ff8888; "
            "border: 1px solid #8a4a4a; border-radius: 3px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background-color: #8a3a3a; }"
        )
        self.stop_btn.clicked.connect(lambda: self.signals.sig_playback_stop.emit())
        time_row.addWidget(self.stop_btn)

        self.time_label = QLabel("00:00")
        self.time_label.setFixedWidth(50)
        self.time_label.setStyleSheet("color: #aaa; font-size: 11px;")
        time_row.addWidget(self.time_label)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 10000)  # 0.01s rozdzielczość, max 100s
        self.seek_slider.setTickPosition(QSlider.NoTicks)
        self.seek_slider.valueChanged.connect(self._on_seek)
        time_row.addWidget(self.seek_slider, 1)

        self.duration_label = QLabel("00:00")
        self.duration_label.setFixedWidth(50)
        self.duration_label.setAlignment(Qt.AlignRight)
        self.duration_label.setStyleSheet("color: #aaa; font-size: 11px;")
        time_row.addWidget(self.duration_label)

        layout.addLayout(time_row)

    # ── Slot: nowa klatka podglądu ─────────────────────────────────────

    def on_frame_ready(self, pixmap: QPixmap) -> None:
        """Odbiera QPixmap z kontrolera i wyświetla."""
        if pixmap is None or pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #333;"
        )
        # Zapisz rozmiar i offset wyświetlonej pixmapy (do przeliczania współrzędnych)
        pix_size = scaled.size()
        self._pixmap_size = (pix_size.width(), pix_size.height())
        label_size = self.image_label.size()
        ox = (label_size.width() - pix_size.width()) // 2
        oy = (label_size.height() - pix_size.height()) // 2
        self._pixmap_offset = (ox, oy)

    def set_bboxes(self, bboxes: dict[str, tuple[int, int, int, int]], orig_w: int, orig_h: int) -> None:
        """Odbiera bounding boxy wskaźników z kontrolera (w pikselach oryginalnego obrazu)."""
        self._bboxes = bboxes
        self._original_size = (orig_w, orig_h)

    def eventFilter(self, obj, event) -> bool:
        """Przechwytuje zdarzenia myszy na image_label."""
        if obj is self.image_label and event.type() in (
            QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease,
        ):
            me = event  # type: QMouseEvent
            # Współrzędne względem labela
            lx, ly = me.position().x(), me.position().y()
            nx, ny = self._norm_from_label(lx, ly)
            in_pixmap = 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0

            if event.type() == QEvent.MouseButtonPress and me.button() == Qt.LeftButton:
                if in_pixmap:
                    key = self._hit_test(nx, ny)
                    if key:
                        self._dragging_key = key
                        self.signals.sig_indicator_clicked.emit(key)
                        return True
                return super().eventFilter(obj, event)

            if event.type() == QEvent.MouseMove and self._dragging_key:
                if in_pixmap:
                    nx = max(0.0, min(1.0, nx))
                    ny = max(0.0, min(1.0, ny))
                    self.signals.sig_indicator_moved.emit(self._dragging_key, nx, ny)
                    return True
                return super().eventFilter(obj, event)

            if event.type() == QEvent.MouseButtonRelease:
                self._dragging_key = None
                return super().eventFilter(obj, event)

        return super().eventFilter(obj, event)

    def _norm_from_label(self, label_x: int, label_y: int) -> tuple[float, float]:
        """Przelicza współrzędne w labelu na znormalizowane (0..1) w oryginalnym obrazie."""
        pw, ph = self._pixmap_size
        ox, oy = self._pixmap_offset
        # Współrzędne względem pixmapy
        px = (label_x - ox) / pw if pw else 0.0
        py = (label_y - oy) / ph if ph else 0.0
        return (px, py)

    def _hit_test(self, nx: float, ny: float) -> str | None:
        """Sprawdza który wskaźnik został kliknięty.

        nx, ny to współrzędne znormalizowane (0..1) względem oryginalnego obrazu.
        Bboxy w self._bboxes są w pikselach oryginalnego obrazu.
        """
        ow, oh = self._original_size
        if ow <= 0 or oh <= 0:
            return None
        # Przelicz znormalizowane współrzędne na piksele oryginału
        click_x = nx * ow
        click_y = ny * oh
        for key, (bx, by, bw, bh) in self._bboxes.items():
            if bx <= click_x <= bx + bw and by <= click_y <= by + bh:
                return key
        return None

    # ── Slot: długość wideo ────────────────────────────────────────────

    def on_duration_ready(self, duration_s: float) -> None:
        """Ustawia maksymalną wartość suwaka na podstawie długości wideo."""
        self._duration_s = max(duration_s, 1.0)
        self.seek_slider.setRange(0, int(self._duration_s * 100))
        total_m = int(self._duration_s // 60)
        total_s = int(self._duration_s % 60)
        self.duration_label.setText(f"{total_m:02d}:{total_s:02d}")

    # ── Slot: przesunięcie suwaka ──────────────────────────────────────

    def _on_seek(self, value: int) -> None:
        seconds = value / 100.0
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        self.time_label.setText(f"{mins:02d}:{secs:02d}")
        self.signals.sig_seek_changed.emit(seconds)
