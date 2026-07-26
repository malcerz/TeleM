"""TrimBar — pasek wycinania fragmentów wideo.

Pozwala zaznaczyć fragment A-B i wyciąć go. Wycięte fragmenty
są wyświetlane jako przyciemnione na pasku.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QCursor
from PySide6.QtWidgets import QWidget


class TrimBar(QWidget):
    """Pasek zakresu z możliwością wycinania fragmentów."""

    # Emitowany gdy użytkownik zmienił znacznik A lub B
    sig_marks_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration_s: float = 100.0
        self._cut_regions: list[tuple[float, float]] = []
        # Tymczasowe znaczniki do wycięcia
        self._mark_a: float | None = None
        self._mark_b: float | None = None
        # Który znacznik jest przeciągany
        self._dragging: str | None = None  # "A" lub "B"

        self.setMinimumHeight(28)
        self.setMaximumHeight(28)
        self.setMouseTracking(True)
        self.setToolTip(
            "Kliknij na pasek, aby ustawić znacznik A (początek cięcia).\n"
            "Kliknij ponownie, aby ustawić znacznik B (koniec cięcia).\n"
            "Następnie kliknij ✂, aby wyciąć zaznaczony fragment."
        )
        self.setCursor(QCursor(Qt.PointingHandCursor))

    # ── API ─────────────────────────────────────────────────────────────

    def set_duration(self, duration_s: float) -> None:
        self._duration_s = max(1.0, duration_s)
        self.update()

    def set_cut_regions(self, regions: list[tuple[float, float]]) -> None:
        self._cut_regions = list(regions)
        self._mark_a = None
        self._mark_b = None
        self.update()

    def get_cut_regions(self) -> list[tuple[float, float]]:
        return list(self._cut_regions)

    def get_selection(self) -> tuple[float, float] | None:
        """Zwróć (start_s, end_s) zaznaczenia A-B, lub None jeśli niekompletne."""
        if self._mark_a is None or self._mark_b is None:
            return None
        a = min(self._mark_a, self._mark_b)
        b = max(self._mark_a, self._mark_b)
        if b - a < 0.1:
            return None
        return (a, b)

    def clear_marks(self) -> None:
        self._mark_a = None
        self._mark_b = None
        self.update()

    # ── Malowanie ───────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 4
        bar_y = margin
        bar_h = h - 2 * margin

        # Tło paska
        painter.fillRect(0, 0, w, h, QColor(30, 30, 30))

        # Główny pasek
        painter.fillRect(margin, bar_y, w - 2 * margin, bar_h, QColor(50, 50, 50))

        # Rysuj wycięte regiony (przyciemnione)
        for start_s, end_s in self._cut_regions:
            x1 = margin + int((w - 2 * margin) * start_s / self._duration_s)
            x2 = margin + int((w - 2 * margin) * end_s / self._duration_s)
            painter.fillRect(x1, bar_y, x2 - x1, bar_h, QColor(25, 25, 25))
            # Przekreślenie (ukośne linie)
            pen = QPen(QColor(80, 30, 30), 1)
            painter.setPen(pen)
            for x in range(x1, x2, 4):
                painter.drawLine(x, bar_y, x + 4, bar_y + bar_h)

        # Rysuj znaczniki A i B
        pen_mark = QPen(QColor(255, 200, 50), 2)
        painter.setPen(pen_mark)

        if self._mark_a is not None:
            x = margin + int((w - 2 * margin) * self._mark_a / self._duration_s)
            painter.drawLine(x, bar_y, x, bar_y + bar_h)
            painter.setFont(QFont("sans-serif", 8))
            painter.drawText(x - 8, bar_y - 2, 18, 12, Qt.AlignCenter, "A")

        if self._mark_b is not None:
            x = margin + int((w - 2 * margin) * self._mark_b / self._duration_s)
            painter.drawLine(x, bar_y, x, bar_y + bar_h)
            painter.setFont(QFont("sans-serif", 8))
            painter.drawText(x - 8, bar_y - 2, 18, 12, Qt.AlignCenter, "B")

        # Zakres A-B (podświetlenie na czerwono)
        if self._mark_a is not None and self._mark_b is not None:
            a = min(self._mark_a, self._mark_b)
            b = max(self._mark_a, self._mark_b)
            x1 = margin + int((w - 2 * margin) * a / self._duration_s)
            x2 = margin + int((w - 2 * margin) * b / self._duration_s)
            painter.fillRect(x1, bar_y, x2 - x1, bar_h, QColor(200, 50, 50, 80))

        painter.end()

    # ── Obsługa myszy ──────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        sec = self._pos_to_seconds(event.position().x())
        if sec is None:
            return

        # Sprawdź czy kliknięto blisko istniejącego znacznika (przeciąganie)
        threshold = 0.02 * self._duration_s  # 2% szerokości
        if self._mark_a is not None and abs(sec - self._mark_a) < threshold:
            self._dragging = "A"
            return
        if self._mark_b is not None and abs(sec - self._mark_b) < threshold:
            self._dragging = "B"
            return

        # Ustaw znacznik A jeśli pusty, B jeśli A już jest
        if self._mark_a is None:
            self._mark_a = max(0.0, min(self._duration_s, sec))
            self._mark_b = None
        elif self._mark_b is None:
            self._mark_b = max(0.0, min(self._duration_s, sec))
            self._emit_if_ready()
        else:
            # Oba znaczniki ustawione — reset i ustaw A od nowa
            self._mark_a = max(0.0, min(self._duration_s, sec))
            self._mark_b = None
        self.sig_marks_changed.emit()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging is None:
            return
        sec = self._pos_to_seconds(event.position().x())
        if sec is None:
            return
        sec = max(0.0, min(self._duration_s, sec))

        if self._dragging == "A":
            self._mark_a = sec
        elif self._dragging == "B":
            self._mark_b = sec
        self.sig_marks_changed.emit()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = None

    # ── Pomocnicze ─────────────────────────────────────────────────────

    def _pos_to_seconds(self, x: float) -> float | None:
        margin = 4
        w = self.width()
        if w <= 2 * margin:
            return None
        rel = (x - margin) / (w - 2 * margin)
        return rel * self._duration_s
