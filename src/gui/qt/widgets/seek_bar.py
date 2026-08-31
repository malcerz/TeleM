"""SeekBar — zwykły pasek przewijania podglądu.

Zakres eksportu jest ustawiany wyłącznie w zakładce Rendering/Export. Pasek
zachowuje wewnętrzne API mapowania zakresów dla kompatybilności z modelem
eksportu, ale nie eksponuje markerów, zaznaczenia ani interakcji A/B.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF, QTimer
from PySide6.QtGui import QPainter, QColor, QPolygonF, QCursor
from PySide6.QtWidgets import QWidget


class SeekBar(QWidget):
    """Pasek przewijania z playheadem; bez UI wyboru zakresu cięcia."""

    # Emitowany gdy użytkownik przeciągnął pasek (seeking)
    sig_position_changed = Signal(float)
    # Emitowany gdy zmienił się zakres A/B
    sig_range_changed = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration_s: float = 100.0           # oryginalna długość
        self._effective_duration_s: float = 100.0 # po odjęciu wycięć
        self._position_s: float = 0.0             # efektywna pozycja seeka
        self._mark_a: float = 0.0                 # znacznik A (efektywny)
        self._mark_b: float = 100.0               # znacznik B (efektywny)
        self._dragging: str | None = None         # None | "seek"
        self._cut_regions: list[tuple[float, float]] = []
        self._has_selection = False

        self._pending_seek_s: float = 0.0
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(50)  # 50ms debounce
        self._seek_timer.timeout.connect(self._emit_debounced_seek)

        self.setMinimumHeight(26)
        self.setMaximumHeight(26)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip("Przeciągnij pasek — przewijanie podglądu.")

    # ═════════════════════════════════════════════════════════════════════
    # API
    # ═════════════════════════════════════════════════════════════════════

    def set_duration(self, duration_s: float) -> None:
        """Ustaw długość nowego wideo i wyczyść poprzednie zaznaczenie."""
        self._duration_s = max(1.0, duration_s)
        self._effective_duration_s = self._duration_s
        self._position_s = 0.0
        self._mark_a = 0.0
        self._mark_b = self._effective_duration_s
        self._has_selection = False
        self.update()

    def set_position(self, seconds: float) -> None:
        """Ustaw pozycję seeka w efektywnym czasie (NIE emituje sygnału)."""
        self._position_s = max(0.0, min(self._effective_duration_s, seconds))
        self.update()

    def get_position(self) -> float:
        """Zwróć bieżącą pozycję seeka (efektywny czas)."""
        return self._position_s

    def get_effective_duration(self) -> float:
        """Zwróć efektywną długość (po odjęciu wycięć)."""
        return self._effective_duration_s

    def has_selection(self) -> bool:
        """Zwróć, czy użytkownik ustawił zakres A-B do wycięcia."""
        return self._has_selection

    def clear_selection(self) -> None:
        """Usuń bieżące zaznaczenie A-B bez zmiany zatwierdzonych cięć."""
        self._mark_a = 0.0
        self._mark_b = self._effective_duration_s
        self._has_selection = False
        self.update()

    def set_range(self, a: float, b: float) -> None:
        """Ustaw zakres A-B w efektywnym czasie (NIE emituje sygnału)."""
        self._mark_a = max(0.0, min(self._effective_duration_s, a))
        self._mark_b = max(0.0, min(self._effective_duration_s, b))
        self._has_selection = True
        self.update()

    def get_range(self) -> tuple[float, float]:
        """Zwróć (start_s, end_s) bieżącego zakresu A-B (efektywny czas)."""
        return (min(self._mark_a, self._mark_b), max(self._mark_a, self._mark_b))

    def set_cut_regions(self, regions: list[tuple[float, float]]) -> None:
        """Ustaw listę zatwierdzonych wycięć i przelicz efektywną długość."""
        self._cut_regions = sorted(
            (max(0.0, start), min(self._duration_s, end))
            for start, end in regions
            if end > start
        )
        total_cut = sum(ce - cs for cs, ce in self._cut_regions)
        self._effective_duration_s = max(1.0, self._duration_s - total_cut)
        self._position_s = min(self._position_s, self._effective_duration_s)
        self.clear_selection()

    # ── Konwersja efektywny ↔ oryginalny czas ──────────────────────────

    def eff_to_orig(self, eff_s: float) -> float:
        """Mapuj pozycję na skróconej osi czasu → oryginalny czas.
        Gdy trafi na granicę cięcia, przeskakuje za nie.
        """
        orig = 0.0
        remaining = eff_s
        for cs, ce in sorted(self._cut_regions, key=lambda x: x[0]):
            visible = cs - orig
            if remaining < visible:
                return orig + remaining
            remaining -= visible
            orig = ce  # skip past the cut
        return orig + remaining

    def orig_to_eff(self, orig_s: float) -> float:
        """Mapuj oryginalny czas → pozycję na skróconej osi czasu.
        Jeśli oryginalny czas jest wewnątrz cięcia, zwraca pozycję
        na początku cięcia (w czasie efektywnym).
        """
        eff = 0.0
        prev_end = 0.0
        for cs, ce in sorted(self._cut_regions, key=lambda x: x[0]):
            if orig_s < cs:
                return eff + (orig_s - prev_end)
            eff += cs - prev_end
            if orig_s <= ce:
                return eff
            prev_end = ce
        return eff + (orig_s - prev_end)

    # ═════════════════════════════════════════════════════════════════════
    # Geometria
    # ═════════════════════════════════════════════════════════════════════

    @property
    def _margin(self) -> int:
        return 4

    @property
    def _bar_y(self) -> int:
        """Y środka paska (toru)."""
        return 6

    @property
    def _bar_h(self) -> int:
        """Wysokość paska."""
        return 5

    def _sec_to_x(self, seconds: float) -> float:
        """Przelicz sekundy (efektywne) na współrzędną X."""
        m = self._margin
        w = self.width() - 2 * m
        eff = self._effective_duration_s
        if eff <= 0 or w <= 0:
            return float(m)
        return m + (seconds / eff) * w

    def _x_to_sec(self, x: float) -> float:
        """Przelicz współrzędną X na sekundy (efektywne)."""
        m = self._margin
        w = self.width() - 2 * m
        eff = self._effective_duration_s
        if w <= 0:
            return 0.0
        clamped = max(float(m), min(float(self.width() - m), x))
        return ((clamped - m) / w) * eff

    # ═════════════════════════════════════════════════════════════════════
    # Malowanie
    # ═════════════════════════════════════════════════════════════════════

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        m = self._margin
        bar_y = self._bar_y
        bar_h = self._bar_h
        dur = self._effective_duration_s

        # Tło (przezroczyste)
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))

        # --- Tor paska ---
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(50, 50, 50))
        painter.drawRoundedRect(m, bar_y, w - 2 * m, bar_h, 2, 2)

        # --- Znacznik pozycji (thumb) ---
        if dur > 0:
            px = self._sec_to_x(self._position_s)
            px = max(m + 1, min(w - m - 1, px))
            painter.setBrush(QColor(180, 220, 255))
            # mały diament
            tri = QPolygonF()
            tri.append(QPointF(px, bar_y - 2))
            tri.append(QPointF(px + 4, bar_y + bar_h // 2))
            tri.append(QPointF(px, bar_y + bar_h + 2))
            tri.append(QPointF(px - 4, bar_y + bar_h // 2))
            painter.drawPolygon(tri)

        painter.end()

    # ═════════════════════════════════════════════════════════════════════
    # Obsługa myszy
    # ═════════════════════════════════════════════════════════════════════

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        x = event.position().x()
        self._dragging = "seek"
        # Natychmiastowy seek do klikniętej pozycji.
        sec = self._x_to_sec(x)
        sec = max(0.0, min(self._effective_duration_s, sec))
        self._position_s = sec
        self.sig_position_changed.emit(sec)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging is None:
            return
        x = event.position().x()
        sec = self._x_to_sec(x)
        sec = max(0.0, min(self._effective_duration_s, sec))

        if self._dragging == "seek":
            self._position_s = sec
            self._pending_seek_s = sec
            self._seek_timer.start()  # restart debounce
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging is not None:
            if self._dragging == "seek":
                self._seek_timer.stop()
                self.sig_position_changed.emit(self._position_s)
        self._dragging = None
        self.update()

    def _emit_debounced_seek(self) -> None:
        """Emituje sig_position_changed po upływie debounce (przeciąganie)."""
        self.sig_position_changed.emit(self._pending_seek_s)
