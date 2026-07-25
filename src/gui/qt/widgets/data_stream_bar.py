"""Panel dynamicznych przycisków — generowany z listy DataStream.

Przyciski tworzone są WYŁĄCZNIE z listy DataStream przekazanej
przez kontroler — nigdy nie są wpisane na stałe.
Używa FlowLayout — przyciski układają się od lewej do prawej,
zawijając do nowego rzędu gdy brak miejsca w poziomie.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize, QPoint
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QPushButton,
    QHBoxLayout, QLayout, QSizePolicy,
)

from src.gui.qt.models import DataStream
from src.gui.qt.signals import get_signals


# ── FlowLayout ─────────────────────────────────────────────────────────────


class _LineBreak(QWidget):
    """Niewidoczny element wymuszający nowy wiersz w FlowLayout."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(0)

    def sizeHint(self) -> QSize:
        return QSize(9999, 0)


class FlowLayout(QLayout):
    """Układ przepływowy — elementy układają się od lewej do prawej,
    a gdy brakuje miejsca w poziomie, zawijają do nowego rzędu."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), False)

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            mins = item.minimumSize()
            size = size.expandedTo(mins)
        size += QSize(2 * self.contentsMargins().top(),
                      2 * self.contentsMargins().top())
        return size

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, True)

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        """Układa elementy w przepływie. Zwraca całkowitą wysokość."""
        m = self.contentsMargins()
        left = rect.x() + m.left()
        top = rect.y() + m.top()
        right = rect.x() + rect.width() - m.right()
        spacing = self.spacing()
        if spacing < 0:
            spacing = 6

        x = left
        y = top
        row_height = 0
        total_height = 0

        for item in self._items:
            widget = item.widget()
            if widget and not widget.isVisible():
                continue
            hint = item.sizeHint()
            item_w = hint.width()
            item_h = hint.height()

            if x + item_w > right and x > left:
                # Zawijamy do nowego rzędu
                x = left
                y += row_height + spacing
                total_height += row_height + spacing
                row_height = 0

            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(item_w, item_h)))
            x += item_w + spacing
            row_height = max(row_height, item_h)

        total_height += row_height
        return total_height + m.top() + m.bottom()


# Kategorie → kolory przycisków
CATEGORY_STYLES: dict[str, str] = {
    "gps":    "#0078d4",
    "sensor": "#d44000",
    "camera": "#10893e",
    "other":  "#666666",
}


class DataStreamBar(QWidget):
    """Pasek dynamicznych przycisków reprezentujących strumienie danych."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._buttons: dict[str, QPushButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 6)

        # Header z przyciskami zarządzania układem
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        def _btn_style(bg, fg, border):
            return (
                f"QPushButton {{"
                f"  background-color: {bg}; color: {fg};"
                f"  border: 1px solid {border}; border-radius: 3px;"
                f"  padding: 2px 6px; font-size: 9px; font-weight: bold;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: {self._lighten(bg)};"
                f"}}"
                f"QPushButton:pressed {{"
                f"  background-color: {self._darken(bg)};"
                f"}}"
            )

        self.save_btn = QPushButton("Zapisz preset")
        self.save_btn.setStyleSheet(_btn_style("#1a5a1a", "#88ff88", "#2a8a2a"))
        self.save_btn.clicked.connect(lambda: self.signals.sig_save_preset.emit())
        header_layout.addWidget(self.save_btn)

        self.load_btn = QPushButton("Wczytaj preset")
        self.load_btn.setStyleSheet(_btn_style("#1a3a5a", "#88bbff", "#2a5a8a"))
        self.load_btn.clicked.connect(lambda: self.signals.sig_load_preset.emit())
        header_layout.addWidget(self.load_btn)

        self.reset_btn = QPushButton("Resetuj układ")
        self.reset_btn.setStyleSheet(_btn_style("#5a0000", "#ff8888", "#800000"))
        self.reset_btn.clicked.connect(
            lambda: self.signals.sig_reset_layout.emit()
        )
        header_layout.addWidget(self.reset_btn)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Scrollowalny obszar na przyciski
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMaximumHeight(140)
        scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #333; background: #1e1e1e; }"
        )

        self.button_widget = QWidget()
        self.button_widget.setStyleSheet("background: #1e1e1e;")
        self.flow = FlowLayout(self.button_widget)
        self.flow.setSpacing(4)
        self.flow.setContentsMargins(6, 6, 6, 6)

        scroll.setWidget(self.button_widget)
        layout.addWidget(scroll)

        # Placeholder (pokazywany gdy brak danych)
        self.placeholder = QLabel(
            "Po wczytaniu danych w zakładce Wczytywanie\n"
            "pojawią się tutaj przyciski.\n"
            "Kliknij przycisk, aby dodać wskaźnik\n"
            "na podglądzie i edytować jego właściwości."
        )
        self.placeholder.setStyleSheet(
            "color: #888; font-style: italic; padding: 16px;"
        )
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder)

    def on_streams_ready(self, streams: list[DataStream]) -> None:
        """Kontroler wysłał listę dostępnych strumieni — utwórz przyciski."""
        # Wyczyść stare przyciski
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()

        # Wyczyść flow
        while self.flow.count():
            item = self.flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if not streams:
            self.placeholder.setText("Brak dostępnych danych telemetrycznych.")
            self.placeholder.setVisible(True)
            return

        self.placeholder.setVisible(False)

        def _add_button(stream: DataStream) -> None:
            btn_text = f"{stream.display_name}\n{stream.source.upper()}"
            btn = QPushButton(btn_text)
            btn.setMinimumHeight(26)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            btn.setToolTip(
                f"Źródło: {stream.source.upper()}\n"
                f"Kategoria: {stream.category}\n"
                f"Próbek: {stream.sample_count}\n"
                f"Zakres: {stream.value_range[0]:.1f} – "
                f"{stream.value_range[1]:.1f} {stream.unit}"
            )
            color = CATEGORY_STYLES.get(stream.category, "#666")
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {color}; color: white;"
                f"  border: none; border-radius: 3px; padding: 1px 4px;"
                f"  font-size: 9px; font-weight: bold;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: {self._lighten(color)};"
                f"}}"
                f"QPushButton:pressed {{"
                f"  background-color: {self._darken(color)};"
                f"}}"
            )
            key = stream.key
            btn.clicked.connect(
                lambda checked=False, k=key: self.signals.sig_stream_clicked.emit(k)
            )
            self.flow.addWidget(btn)
            self._buttons[stream.key] = btn

        def _line_break() -> None:
            """Wymusza nowy wiersz — niewidoczny element na całą szerokość."""
            self.flow.addWidget(_LineBreak())

        # GPMF (bez Mapy)
        for s in streams:
            if s.source == "gpmf" and s.key != "track_map":
                _add_button(s)

        # FIT / GPX (nowy wiersz)
        if any(s.source in ("fit", "gpx") for s in streams):
            _line_break()
            for s in streams:
                if s.source in ("fit", "gpx"):
                    _add_button(s)

        # Mapa (nowy wiersz pod FIT)
        mapa = next((s for s in streams if s.key == "track_map"), None)
        if mapa:
            _line_break()
            btn = QPushButton("Mapa")
            btn.setMinimumHeight(26)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            btn.setToolTip("Mapa GPS – kliknij by dodać na podgląd")
            color = "#5a5a5a"
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {color}; color: white;"
                f"  border: none; border-radius: 3px; padding: 1px 4px;"
                f"  font-size: 9px; font-weight: bold;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: {self._lighten(color)};"
                f"}}"
                f"QPushButton:pressed {{"
                f"  background-color: {self._darken(color)};"
                f"}}"
            )
            btn.clicked.connect(
                lambda: self.signals.sig_stream_clicked.emit("track_map")
            )
            self.flow.addWidget(btn)
            self._buttons["track_map"] = btn

    @staticmethod
    def _lighten(hex_color: str) -> str:
        """Rozjaśnij kolor hex o 30%."""
        hex_color = hex_color.lstrip("#")
        r = min(255, int(int(hex_color[:2], 16) * 1.3))
        g = min(255, int(int(hex_color[2:4], 16) * 1.3))
        b = min(255, int(int(hex_color[4:6], 16) * 1.3))
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _darken(hex_color: str) -> str:
        """Przyciemnij kolor hex o 20%."""
        hex_color = hex_color.lstrip("#")
        r = int(int(hex_color[:2], 16) * 0.8)
        g = int(int(hex_color[2:4], 16) * 0.8)
        b = int(int(hex_color[4:6], 16) * 0.8)
        return f"#{r:02x}{g:02x}{b:02x}"
