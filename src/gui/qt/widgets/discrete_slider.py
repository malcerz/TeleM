"""Dyskretny suwak z etykietami dla ustawień eksportu (rozdzielczość, presety, FPS).

Kompatybilny z interfejsem QComboBox (currentText, currentData, setCurrentText,
setCurrentIndex, currentIndexChanged, findData, findText).
"""

from __future__ import annotations

import re
from typing import Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel, QPushButton, QToolButton,
    QLineEdit, QSizePolicy, QStyle, QApplication,
)
from PySide6.QtGui import QCursor, QFont


class ClickableLabel(QLabel):
    """Etykieta klikalna, kliknięcie przestawia suwak na dany indeks."""

    clicked = Signal(int)

    def __init__(self, text: str, index: int, parent=None):
        super().__init__(text, parent)
        self.index = index
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setAlignment(Qt.AlignCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class DiscreteSlider(QWidget):
    """Dyskretny suwak z czytelnymi etykietami pozycji."""

    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)

    def __init__(
        self,
        items: list[str | tuple[str, Any]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, Any]] = []
        self._labels: list[ClickableLabel] = []

        self._vbox = QVBoxLayout(self)
        self._vbox.setContentsMargins(0, 2, 0, 2)
        self._vbox.setSpacing(1)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(1)
        self._slider.setTickPosition(QSlider.TicksBelow)
        self._slider.setTickInterval(1)
        self._slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 6px; background: #bbb; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #d44000; border-radius: 3px; }"
            "QSlider::handle:horizontal { background: #d44000; border: 1px solid #aa3000; "
            "width: 16px; margin-top: -5px; margin-bottom: -5px; border-radius: 8px; }"
            "QSlider::handle:horizontal:hover { background: #e45010; }"
        )
        self._slider.valueChanged.connect(self._on_slider_value_changed)
        self._vbox.addWidget(self._slider)

        self._labels_widget = QWidget()
        self._labels_layout = QHBoxLayout(self._labels_widget)
        self._labels_layout.setContentsMargins(4, 0, 4, 0)
        self._labels_layout.setSpacing(0)
        self._vbox.addWidget(self._labels_widget)

        if items:
            self.addItems(items)

    def clear(self) -> None:
        self._items.clear()
        for lbl in self._labels:
            self._labels_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._labels.clear()
        self._slider.setMaximum(0)

    def addItem(self, text: str, data: Any = None) -> None:
        self.addItems([(text, data if data is not None else text)])

    def addItems(self, items: list[str | tuple[str, Any]]) -> None:
        start_idx = len(self._items)
        for i, it in enumerate(items):
            if isinstance(it, tuple):
                text, data = it
            else:
                text, data = str(it), str(it)
            idx = start_idx + i
            self._items.append((text, data))
            lbl = ClickableLabel(text, idx)
            lbl.setStyleSheet("color: #666; font-size: 11px; font-weight: normal;")
            lbl.clicked.connect(self.setCurrentIndex)
            self._labels.append(lbl)
            self._labels_layout.addWidget(lbl, 1)

        max_idx = max(0, len(self._items) - 1)
        self._slider.blockSignals(True)
        self._slider.setMaximum(max_idx)
        self._slider.blockSignals(False)
        self._highlight_active_label(self._slider.value())

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:
        return self._slider.value()

    def currentText(self) -> str:
        idx = self.currentIndex()
        if 0 <= idx < len(self._items):
            return self._items[idx][0]
        return ""

    def currentData(self) -> Any:
        idx = self.currentIndex()
        if 0 <= idx < len(self._items):
            return self._items[idx][1]
        return None

    def itemText(self, index: int) -> str:
        if 0 <= index < len(self._items):
            return self._items[index][0]
        return ""

    def itemData(self, index: int) -> Any:
        if 0 <= index < len(self._items):
            return self._items[index][1]
        return None

    def setCurrentIndex(self, index: int) -> None:
        index = max(0, min(index, len(self._items) - 1))
        if hasattr(self, "_disabled_indices") and index in self._disabled_indices:
            # find closest enabled index, preferring lower (clamp down)
            clamped = None
            for fallback in range(index - 1, -1, -1):
                if fallback not in self._disabled_indices:
                    clamped = fallback
                    break
            if clamped is None:
                for fallback in range(index + 1, len(self._items)):
                    if fallback not in self._disabled_indices:
                        clamped = fallback
                        break
            if clamped is not None:
                index = clamped
        if self._slider.value() != index:
            self._slider.setValue(index)
        else:
            self._highlight_active_label(index)

    def setCurrentText(self, text: str) -> None:
        idx = self.findText(text)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            # Fallback to data matching
            idx_d = self.findData(text)
            if idx_d >= 0:
                self.setCurrentIndex(idx_d)

    def findText(self, text: str) -> int:
        target = str(text).strip().lower()
        for i, (t, _) in enumerate(self._items):
            if t.strip().lower() == target:
                return i
        return -1

    def findData(self, data: Any) -> int:
        target = str(data).strip().lower()
        for i, (_, d) in enumerate(self._items):
            if str(d).strip().lower() == target or str(d) == str(data):
                return i
        return -1

    def _on_slider_value_changed(self, value: int) -> None:
        if hasattr(self, "_disabled_indices") and value in self._disabled_indices:
            # snap to closest enabled index
            clamped = None
            for fallback in range(value - 1, -1, -1):
                if fallback not in self._disabled_indices:
                    clamped = fallback
                    break
            if clamped is None:
                for fallback in range(value + 1, len(self._items)):
                    if fallback not in self._disabled_indices:
                        clamped = fallback
                        break
            if clamped is not None and clamped != value:
                self._slider.setValue(clamped)
                return
        self._highlight_active_label(value)
        self.currentIndexChanged.emit(value)
        self.currentTextChanged.emit(self.currentText())

    def _highlight_active_label(self, active_index: int) -> None:
        for i, lbl in enumerate(self._labels):
            is_disabled = hasattr(self, "_disabled_indices") and i in self._disabled_indices
            if is_disabled:
                if i == active_index:
                    lbl.setStyleSheet("color: #c0392b; font-size: 11px; font-weight: bold; text-decoration: line-through;")
                else:
                    lbl.setStyleSheet("color: #aaa; font-size: 11px; font-weight: normal; text-decoration: line-through;")
            elif i == active_index:
                lbl.setStyleSheet("color: #d44000; font-size: 11px; font-weight: bold;")
            else:
                lbl.setStyleSheet("color: #666; font-size: 11px; font-weight: normal;")

    def setItemEnabled(self, index: int, enabled: bool, tooltip: str = "") -> None:
        if not hasattr(self, "_disabled_indices"):
            self._disabled_indices = set()
        if 0 <= index < len(self._items):
            if enabled:
                self._disabled_indices.discard(index)
            else:
                self._disabled_indices.add(index)
            lbl = self._labels[index]
            lbl.setToolTip(tooltip if not enabled else "")
            if not enabled and self.currentIndex() == index:
                self.setCurrentIndex(index)
            self._highlight_active_label(self._slider.value())

    def isItemEnabled(self, index: int) -> bool:
        if not hasattr(self, "_disabled_indices"):
            return True
        return index not in self._disabled_indices

    def setToolTip(self, tip: str) -> None:
        super().setToolTip(tip)
        self._slider.setToolTip(tip)


class BitrateControl(QWidget):
    """Spójny zestaw kontrolek bitrate: [←] ── SLIDER ── [→] [ pole wartości ]."""

    valueChanged = Signal(int)
    textChanged = Signal(str)

    def __init__(
        self,
        min_mbps: int = 5,
        max_mbps: int = 120,
        default_mbps: int = 40,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._min_mbps = int(min_mbps)
        self._max_mbps = int(max_mbps)
        self._updating = False

        hlayout = QHBoxLayout(self)
        hlayout.setContentsMargins(0, 0, 0, 0)
        hlayout.setSpacing(6)

        style = QApplication.style() if QApplication.instance() else self.style()

        # 1. Przycisk -1 Mb/s (lewa strzałka)
        self.btn_left = QToolButton()
        self.btn_left.setFixedSize(24, 24)
        if style:
            self.btn_left.setIcon(style.standardIcon(QStyle.SP_ArrowLeft))
        self.btn_left.setToolTip("Zmniejsz bitrate o 1 Mb/s")
        self.btn_left.setStyleSheet(
            "QToolButton { border: 1px solid #ccc; border-radius: 3px; background: #f8f8f8; padding: 0; }"
            "QToolButton:hover { background: #e8e8e8; border-color: #aaa; }"
            "QToolButton:pressed { background: #d8d8d8; }"
        )
        self.btn_left.clicked.connect(self._on_dec_clicked)
        self.btn_min = self.btn_left  # alias dla zachowania kompatybilności wstecznej
        hlayout.addWidget(self.btn_left)

        # 2. Slider
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(self._min_mbps)
        self.slider.setMaximum(self._max_mbps)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)
        self.slider.setValue(default_mbps)
        self.slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 6px; background: #bbb; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #d44000; border-radius: 3px; }"
            "QSlider::handle:horizontal { background: #d44000; border: 1px solid #aa3000; "
            "width: 16px; margin-top: -5px; margin-bottom: -5px; border-radius: 8px; }"
            "QSlider::handle:horizontal:hover { background: #e45010; }"
        )
        self.slider.valueChanged.connect(self._on_slider_changed)
        hlayout.addWidget(self.slider, 1)

        # 3. Przycisk +1 Mb/s (prawa strzałka)
        self.btn_right = QToolButton()
        self.btn_right.setFixedSize(24, 24)
        if style:
            self.btn_right.setIcon(style.standardIcon(QStyle.SP_ArrowRight))
        self.btn_right.setToolTip("Zwiększ bitrate o 1 Mb/s")
        self.btn_right.setStyleSheet(
            "QToolButton { border: 1px solid #ccc; border-radius: 3px; background: #f8f8f8; padding: 0; }"
            "QToolButton:hover { background: #e8e8e8; border-color: #aaa; }"
            "QToolButton:pressed { background: #d8d8d8; }"
        )
        self.btn_right.clicked.connect(self._on_inc_clicked)
        self.btn_max = self.btn_right  # alias dla zachowania kompatybilności wstecznej
        hlayout.addWidget(self.btn_right)

        # 4. Pole ręcznego wpisu
        self.edit_value = QLineEdit(f"{default_mbps} Mb/s")
        self.edit_value.setFixedWidth(80)
        self.edit_value.setAlignment(Qt.AlignCenter)
        self.edit_value.textEdited.connect(self._on_text_edited)
        self.edit_value.editingFinished.connect(self._on_editing_finished)
        hlayout.addWidget(self.edit_value)

    def _on_dec_clicked(self) -> None:
        self.setValue(self.value() - 1)

    def _on_inc_clicked(self) -> None:
        self.setValue(self.value() + 1)

    def _on_slider_changed(self, val: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.edit_value.setText(f"{val} Mb/s")
        self._updating = False
        self.valueChanged.emit(val)
        self.textChanged.emit(self.text())

    def _on_text_edited(self, text: str) -> None:
        if self._updating:
            return
        # Parse number from text
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if match:
            try:
                num = float(match.group(1))
                val = int(round(num))
                val_clamped = max(self._min_mbps, min(self._max_mbps, val))
                self._updating = True
                self.slider.setValue(val_clamped)
                self._updating = False
                self.valueChanged.emit(val_clamped)
                self.textChanged.emit(self.text())
            except ValueError:
                pass

    def _on_editing_finished(self) -> None:
        val = self.slider.value()
        self.edit_value.setText(f"{val} Mb/s")

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, val: int) -> None:
        val = max(self._min_mbps, min(self._max_mbps, int(val)))
        self._updating = True
        self.slider.setValue(val)
        self.edit_value.setText(f"{val} Mb/s")
        self._updating = False
        self.valueChanged.emit(val)
        self.textChanged.emit(self.text())

    def text(self) -> str:
        """Zwraca bitrate w formacie akceptowanym przez backend (np. '40M')."""
        return f"{self.value()}M"

    def display_text(self) -> str:
        """Zwraca tekst widoczny w polu tekstowym (np. '40 Mb/s')."""
        return self.edit_value.text().strip()

    def setText(self, text: str) -> None:
        text = str(text).strip()
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if match:
            try:
                num = float(match.group(1))
                # Check if it was in bps (e.g. 40000000) or kbps (40000k) or mbps (40M, 40)
                if num > 1000000:
                    val = int(round(num / 1000000.0))
                elif num > 1000:
                    val = int(round(num / 1000.0))
                else:
                    val = int(round(num))
                self.setValue(val)
                return
            except ValueError:
                pass
        self.edit_value.setText(text)

    def setToolTip(self, tip: str) -> None:
        super().setToolTip(tip)
        self.slider.setToolTip(tip)
        self.edit_value.setToolTip(tip)
