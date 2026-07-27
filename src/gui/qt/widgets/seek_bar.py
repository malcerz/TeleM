"""SeekBar — zintegrowany pasek przewijania z znacznikami wycinania A/B.

Zastępuje osobny QSlider + MarkerBar jednym widgetem.
--- same
- Przeciaganie po pasku → seek (zmiana pozycji odtwarzania)
- Przeciaganie zoltego (A) / czerwonego (B) trojkata pod paskiem → zakres wycinania
- Pomaranczowe podswietlenie zakresu A-B na pasku
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QPainter, QColor, QPolygonF, QCursor
from PySide6.QtWidgets import QWidget


class SeekBar(QWidget):
    """Pasek przewijania z wbudowanymi znacznikami A/B wycinania."""

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
        self._dragging: str | None = None         # None | "seek" | "A" | "B"
        self._cut_regions: list[tuple[float, float]] = []

        self.setMinimumHeight(26)
        self.setMaximumHeight(26)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip(
            "Przeciagnij pasek — przewijanie.\n"
            "Przeciagnij zolty (A) / czerwony (B) znacznik — zakres wycinania."
        )

    # ═════════════════════════════════════════════════════════════════════
    # API
    # ═════════════════════════════════════════════════════════════════════

    def set_duration(self, duration_s: float) -> None:
        """Ustaw długość wideo w sekundach."""
        self._duration_s = max(1.0, duration_s)
        self._effective_duration_s = self._duration_s
        if self._mark_b > self._effective_duration_s:
            self._mark_b = self._effective_duration_s
        if self._position_s > self._effective_duration_s:
            self._position_s = self._effective_duration_s
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

    def set_range(self, a: float, b: float) -> None:
        """Ustaw zakres A-B w efektywnym czasie (NIE emituje sygnału)."""
        self._mark_a = max(0.0, min(self._effective_duration_s, a))
        self._mark_b = max(0.0, min(self._effective_duration_s, b))
        self.update()

    def get_range(self) -> tuple[float, float]:
        """Zwróć (start_s, end_s) bieżącego zakresu A-B (efektywny czas)."""
        return (min(self._mark_a, self._mark_b), max(self._mark_a, self._mark_b))

    def set_cut_regions(self, regions: list[tuple[float, float]]) -> None:
        """Ustaw listę zatwierdzonych wycięć i przelicz efektywną długość."""
        self._cut_regions = list(regions)
        total_cut = sum(ce - cs for cs, ce in self._cut_regions)
        self._effective_duration_s = max(1.0, self._duration_s - total_cut)
        if self._position_s > self._effective_duration_s:
            self._position_s = self._effective_duration_s
        if self._mark_b > self._effective_duration_s:
            self._mark_b = self._effective_duration_s
        self.update()

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
        orig_dur = self._duration_s

        # Tło (przezroczyste)
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))

        # --- Tor paska ---
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(50, 50, 50))
        painter.drawRoundedRect(m, bar_y, w - 2 * m, bar_h, 2, 2)

        # --- Zakres A-B (pomarańczowy, pod spodem) ---
        if dur > 0:
            a, b = self.get_range()
            if b - a > 0.01:
                x1 = self._sec_to_x(a)
                x2 = self._sec_to_x(b)
                painter.setBrush(QColor(200, 100, 50, 140))
                painter.drawRoundedRect(
                    int(x1), bar_y, max(1, int(x2 - x1)), bar_h, 2, 2,
                )

        # --- Wycięte fragmenty (ciemnoczerwone, NA WIERZCHU) ---
        if dur > 0:
            for cut_start, cut_end in self._cut_regions:
                cx1 = self._sec_to_x(max(0, cut_start))
                cx2 = self._sec_to_x(min(dur, cut_end))
                if cx2 - cx1 >= 1:
                    painter.setBrush(QColor(160, 40, 40, 220))
                    painter.drawRoundedRect(
                        int(cx1), bar_y, max(1, int(cx2 - cx1)), bar_h, 2, 2,
                    )

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

        # --- Znacznik A (żółty trójkąt pod paskiem) ---
        if dur > 0:
            ax = self._sec_to_x(self._mark_a)
            ax = max(m, min(w - m, ax))
            tri_a = QPolygonF()
            tri_a.append(QPointF(ax, h - 2))
            tri_a.append(QPointF(ax - 5, h - 10))
            tri_a.append(QPointF(ax + 5, h - 10))
            painter.setBrush(QColor(255, 200, 50))
            painter.drawPolygon(tri_a)

            # Etykieta "A"
            painter.setPen(QColor(255, 200, 50))
            fnt = painter.font()
            fnt.setPointSize(7)
            painter.setFont(fnt)
            painter.drawText(int(ax) - 8, h - 14, 16, 8, Qt.AlignCenter, "A")

        # --- Znacznik B (czerwony trójkąt pod paskiem) ---
        if dur > 0:
            bx = self._sec_to_x(self._mark_b)
            bx = max(m, min(w - m, bx))
            tri_b = QPolygonF()
            tri_b.append(QPointF(bx, h - 2))
            tri_b.append(QPointF(bx - 5, h - 10))
            tri_b.append(QPointF(bx + 5, h - 10))
            painter.setBrush(QColor(255, 80, 80))
            painter.drawPolygon(tri_b)

            # Etykieta "B"
            painter.setPen(QColor(255, 80, 80))
            fnt = painter.font()
            fnt.setPointSize(7)
            painter.setFont(fnt)
            painter.drawText(int(bx) - 8, h - 14, 16, 8, Qt.AlignCenter, "B")

        painter.end()

    # ═════════════════════════════════════════════════════════════════════
    # Obsługa myszy
    # ═════════════════════════════════════════════════════════════════════

    def _hit_marker(self, x: float) -> str | None:
        """Sprawdź czy kliknięto w pobliżu znacznika A lub B."""
        if self._effective_duration_s <= 0:
            return None
        sec = self._x_to_sec(x)
        threshold = 0.04 * self._effective_duration_s
        if abs(sec - self._mark_a) < threshold:
            return "A"
        if abs(sec - self._mark_b) < threshold:
            return "B"
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        x = event.position().x()
        hit = self._hit_marker(x)
        if hit:
            self._dragging = hit
        else:
            self._dragging = "seek"
            # Natychmiastowy seek do klikniętej pozycji
            sec = self._x_to_sec(x)
            sec = max(0.0, min(self._duration_s, sec))
            self._position_s = sec
            self.sig_position_changed.emit(sec)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging is None:
            return
        x = event.position().x()
        sec = self._x_to_sec(x)
        sec = max(0.0, min(self._duration_s, sec))

        if self._dragging == "seek":
            self._position_s = sec
            self.sig_position_changed.emit(sec)
        elif self._dragging == "A":
            self._mark_a = sec
            self.sig_range_changed.emit(*self.get_range())
        elif self._dragging == "B":
            self._mark_b = sec
            self.sig_range_changed.emit(*self.get_range())
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging is not None and self._dragging in ("A", "B"):
            self.sig_range_changed.emit(*self.get_range())
        self._dragging = None
        self.update()
