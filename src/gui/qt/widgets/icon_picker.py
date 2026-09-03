"""Visual Icon Picker Widget for TeleM GUI.

Provides a responsive, searchable grid of graphical icon thumbnails for
selecting HUD indicator icons.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QGridLayout, QFrame, QSizePolicy,
    QToolButton,
)

from src.indicators.icons import ICON_NAMES, ICON_LABELS, _PNG_DIR

# Global in-memory cache for QPixmaps to ensure instant UI rendering
_PIXMAP_CACHE: dict[str, QPixmap] = {}


def _get_icon_pixmap(name: str, size: int = 28) -> QPixmap:
    """Load and cache QPixmap for an icon name."""
    cache_key = f"{name}_{size}"
    if cache_key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[cache_key]

    png_path = _PNG_DIR / f"{name}.png"
    if png_path.is_file():
        pm = QPixmap(str(png_path))
        if not pm.isNull():
            scaled = pm.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            _PIXMAP_CACHE[cache_key] = scaled
            return scaled

    # Fallback blank/dot pixmap
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    _PIXMAP_CACHE[cache_key] = pm
    return pm


class IconButton(QToolButton):
    """Square thumbnail button for a single icon in the grid."""

    def __init__(self, icon_key: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.icon_key = icon_key
        self.setFixedSize(38, 38)
        self.setIconSize(QSize(26, 26))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)

        label = ICON_LABELS.get(icon_key, icon_key)
        self.setToolTip(f"{label}\n({icon_key})")

        pix = _get_icon_pixmap(icon_key, 26)
        self.setIcon(QIcon(pix))
        self._apply_style(False)

    def _apply_style(self, selected: bool) -> None:
        if selected:
            self.setStyleSheet(
                "QToolButton {"
                "  background-color: #1e3a8a;"
                "  border: 2px solid #38bdf8;"
                "  border-radius: 4px;"
                "  padding: 2px;"
                "}"
            )
        else:
            self.setStyleSheet(
                "QToolButton {"
                "  background-color: #1e293b;"
                "  border: 1px solid #334155;"
                "  border-radius: 4px;"
                "  padding: 2px;"
                "}"
                "QToolButton:hover {"
                "  background-color: #334155;"
                "  border: 1px solid #64748b;"
                "}"
            )

    def set_selected(self, selected: bool) -> None:
        self.setChecked(selected)
        self._apply_style(selected)


class IconPickerWidget(QWidget):
    """Graphical icon selector with preview, search filter, and thumbnail grid."""

    icon_changed = Signal(str)

    def __init__(self, current_value: str = "none", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_value = str(current_value or "none").strip().lower()
        self._buttons: dict[str, IconButton] = {}
        self._build_ui()
        self.set_value(self._current_value)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(6)

        # ── 1. Top Card: Current Selection & Clear button ──
        preview_card = QFrame()
        preview_card.setStyleSheet(
            "QFrame {"
            "  background-color: #0f172a;"
            "  border: 1px solid #1e293b;"
            "  border-radius: 6px;"
            "  padding: 4px;"
            "}"
        )
        card_layout = QHBoxLayout(preview_card)
        card_layout.setContentsMargins(6, 4, 6, 4)
        card_layout.setSpacing(8)

        # Big Preview Icon
        self.preview_icon = QLabel()
        self.preview_icon.setFixedSize(36, 36)
        self.preview_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_icon.setStyleSheet(
            "background-color: #1e293b; border: 1px solid #334155; border-radius: 4px;"
        )
        card_layout.addWidget(self.preview_icon)

        # Label info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)
        self.lbl_selected_title = QLabel("Wybrana ikona:")
        self.lbl_selected_title.setStyleSheet("color: #94a3b8; font-size: 10px;")
        self.lbl_selected_name = QLabel("Brak")
        self.lbl_selected_name.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 11px;")
        info_layout.addWidget(self.lbl_selected_title)
        info_layout.addWidget(self.lbl_selected_name)
        card_layout.addLayout(info_layout, 1)

        # None / Clear Button
        self.btn_none = QPushButton("Brak ikony")
        self.btn_none.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_none.setStyleSheet(
            "QPushButton {"
            "  background-color: #334155; color: #cbd5e1;"
            "  border: 1px solid #475569; border-radius: 4px;"
            "  padding: 4px 8px; font-size: 10px;"
            "}"
            "QPushButton:hover { background-color: #475569; color: #ffffff; }"
        )
        self.btn_none.clicked.connect(lambda: self._select_icon("none"))
        card_layout.addWidget(self.btn_none)

        main_layout.addWidget(preview_card)

        # ── 2. Search / Filter Bar ──
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Szukaj ikony (np. serce, gopro, bateria)...")
        self.search_input.setStyleSheet(
            "QLineEdit {"
            "  background-color: #1e293b; color: #f8fafc;"
            "  border: 1px solid #334155; border-radius: 4px;"
            "  padding: 4px 6px; font-size: 11px;"
            "}"
            "QLineEdit:focus { border: 1px solid #38bdf8; }"
        )
        self.search_input.textChanged.connect(self._filter_icons)
        main_layout.addWidget(self.search_input)

        # ── 3. Scrollable Icon Grid ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(150)
        scroll.setMaximumHeight(220)
        scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #1e293b; border-radius: 4px; background-color: #0b0f19; }"
            "QScrollBar:vertical { width: 8px; background: #0b0f19; }"
            "QScrollBar::handle:vertical { background: #334155; border-radius: 4px; }"
        )

        grid_container = QWidget()
        grid_container.setStyleSheet("background-color: #0b0f19;")
        self.grid_layout = QGridLayout(grid_container)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        self.grid_layout.setSpacing(4)

        # Populate grid with all valid icons (skipping 'none' which has a dedicated button)
        valid_icons = [name for name in ICON_NAMES if name != "none"]
        cols = 6
        for idx, icon_key in enumerate(valid_icons):
            btn = IconButton(icon_key)
            btn.clicked.connect(lambda checked=False, k=icon_key: self._select_icon(k))
            self._buttons[icon_key] = btn
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(btn, r, c)

        scroll.setWidget(grid_container)
        main_layout.addWidget(scroll, 1)

    def _select_icon(self, icon_key: str) -> None:
        """Handle user icon selection."""
        icon_key = str(icon_key or "none").strip().lower()
        self.set_value(icon_key)
        self.icon_changed.emit(icon_key)

    def set_value(self, icon_key: str) -> None:
        """Update current value and visual states."""
        self._current_value = str(icon_key or "none").strip().lower()

        # Update preview card
        if self._current_value in ("none", "", "0", "false"):
            self.preview_icon.setPixmap(QPixmap())
            self.preview_icon.setText("—")
            self.preview_icon.setStyleSheet(
                "background-color: #1e293b; color: #64748b; font-size: 14px; font-weight: bold; border: 1px solid #334155; border-radius: 4px;"
            )
            self.lbl_selected_name.setText("Brak ikony")
        else:
            pix = _get_icon_pixmap(self._current_value, 28)
            self.preview_icon.setText("")
            self.preview_icon.setPixmap(pix)
            self.preview_icon.setStyleSheet(
                "background-color: #1e293b; border: 1px solid #38bdf8; border-radius: 4px;"
            )
            label = ICON_LABELS.get(self._current_value, self._current_value)
            self.lbl_selected_name.setText(f"{label} ({self._current_value})")

        # Update grid selection highlights
        for key, btn in self._buttons.items():
            btn.set_selected(key == self._current_value)

    def get_value(self) -> str:
        """Return the currently selected icon key."""
        return self._current_value

    def value(self) -> str:
        """Alias for get_value() to match Qt widget conventions."""
        return self._current_value

    def _filter_icons(self, query: str) -> None:
        """Filter grid items in real-time based on search input."""
        q = query.strip().lower()
        cols = 6
        visible_idx = 0
        for icon_key, btn in self._buttons.items():
            label = ICON_LABELS.get(icon_key, "").lower()
            match = (not q) or (q in icon_key.lower()) or (q in label)
            btn.setVisible(match)
            if match:
                self.grid_layout.removeWidget(btn)
                r = visible_idx // cols
                c = visible_idx % cols
                self.grid_layout.addWidget(btn, r, c)
                visible_idx += 1
