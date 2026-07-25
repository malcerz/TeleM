"""Panel właściwości — QStackedWidget z dynamicznymi formularzami.

Dla każdego wskaźnika buduje formularz na podstawie schematu
dostarczonego przez kontroler.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QCheckBox, QComboBox,
    QDoubleSpinBox, QSpinBox, QLineEdit,
    QFormLayout, QHBoxLayout, QPushButton, QColorDialog,
    QSizePolicy, QSpacerItem, QTabWidget,
)

from src.gui.qt.models import FieldSchema
from src.gui.qt.signals import get_signals


class PropertyEditor(QWidget):
    """Panel właściwości dla wybranego wskaźnika.

    Używa QStackedWidget — każda kategoria/typ może mieć własną stronę.
    Obecnie używa jednej strony z dynamicznym formularzem.
    """

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._current_key: str = ""
        self._suppress_emit: bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Nagłówek
        self.header = QLabel("<b>Właściwości</b>")
        self.header.setStyleSheet("font-size: 13px; padding-bottom: 4px;")
        layout.addWidget(self.header)

        self.key_label = QLabel("")
        self.key_label.setStyleSheet(
            "color: #888; font-size: 11px; padding-bottom: 4px;"
        )
        layout.addWidget(self.key_label)

        # Przycisk Usuń
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.delete_btn = QPushButton("Usuń")
        self.delete_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #5a0000; color: #ff8888;"
            "  border: 1px solid #800000; border-radius: 3px;"
            "  padding: 2px 8px; font-size: 10px; font-weight: bold;"
            "}"
            "QPushButton:hover {"
            "  background-color: #7a0000; color: #ffaaaa;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #3a0000;"
            "}"
        )
        self.delete_btn.clicked.connect(
            lambda: self.signals.sig_delete_indicator.emit(self._current_key)
        )
        self.delete_btn.setVisible(False)
        row.addWidget(self.delete_btn)
        row.addStretch()
        layout.addLayout(row)

        # Kontener na formularz (pokazywany gdy są właściwości)
        self.form_container = QWidget()
        self.form_container.setVisible(False)
        layout.addWidget(self.form_container, 1)

        # Placeholder (pokazywany gdy nic nie wybrano)
        self.placeholder = QLabel(
            "Kliknij przycisk danych po lewej,\n"
            "aby wyświetlić właściwości."
        )
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet(
            "color: #888; padding: 20px; font-size: 12px;"
        )
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder)

    def on_properties_ready(
        self, stream_key: str, schema: list[FieldSchema], values: dict,
    ) -> None:
        """Kontroler wysłał schemat i wartości — zbuduj formularz."""
        if not stream_key:
            # Wyczyść panel
            self._current_key = ""
            self.key_label.setText("")
            self.delete_btn.setVisible(False)
            self.placeholder.setVisible(True)
            self.form_container.setVisible(False)
            if self.form_container.layout():
                self._clear_layout(self.form_container.layout())
            return

        self._current_key = stream_key
        self.key_label.setText(f"Wskaźnik: {stream_key}")
        self.delete_btn.setVisible(True)
        self.placeholder.setVisible(False)

        self._build_form(schema, values)
        self.form_container.setVisible(True)

    def _clear_layout(self, layout) -> None:
        """Rekurencyjnie usuwa wszystkie widgety i zagnieżdżone layouty.

        `QLayout.takeAt()` zwraca `None` dla `item.widget()` gdy dany
        element jest zagnieżdżonym layoutem (np. dodanym przez
        `addLayout()`), więc bez rekurencji widgety w takich layoutach
        (np. pola nagłówka w `hform`) nigdy nie były usuwane – zostawały
        jako osierocone dzieci `form_container` i renderowały się pod
        nowo budowanym formularzem (nakładające się/zniekształcone etykiety).

        Nie usuwa samego przekazanego `layout` – tylko jego zawartość.
        Zagnieżdżone layouty (np. `hform`) są usuwane rekurencyjnie, bo są
        tworzone od nowa przy każdym budowaniu formularza.
        """
        while layout.count():
            item = layout.takeAt(0)
            child_widget = item.widget()
            if child_widget is not None:
                child_widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)
                child_layout.deleteLater()

    def _build_form(self, schema: list[FieldSchema], values: dict) -> None:
        """Buduje interfejs z zakładkami: header + QTabWidget."""
        # Wyczyść zawartość starego kontenera i ponownie użyj tego samego
        # layoutu (jego natychmiastowe usunięcie + `QVBoxLayout(...)` od
        # razu skutkowało ostrzeżeniem Qt "already has a layout", bo
        # `deleteLater()` usuwa stary layout dopiero w kolejnej iteracji
        # pętli zdarzeń).
        existing = self.form_container.layout()
        if existing is not None:
            self._clear_layout(existing)
            outer = existing
        else:
            outer = QVBoxLayout(self.form_container)
        outer.setContentsMargins(4, 4, 4, 4)

        # ── Header – pola bez zakładki (tab == "") ────────────────────
        header_fields = [f for f in schema if f.tab == ""]
        if header_fields:
            hform = QFormLayout()
            hform.setSpacing(6)
            for field in header_fields:
                w = self._create_field_widget(field, values.get(field.name))
                if w:
                    hform.addRow(f"{field.label}:", w)
            outer.addLayout(hform)

        # ── Zakładki ──────────────────────────────────────────────────
        tab_order = ["Text", "Labels", "Ticks", "Gauge", "Chart", "Segments", "Shape"]
        grouped: dict[str, list[FieldSchema]] = {t: [] for t in tab_order}
        for field in schema:
            if field.tab in grouped:
                grouped[field.tab].append(field)

        active_tabs = {t: f for t, f in grouped.items() if f}
        if active_tabs:
            tabs = QTabWidget()
            tabs.setStyleSheet(
                "QTabWidget::pane { border: 1px solid #333; }"
                "QTabBar::tab { padding: 3px 8px; font-size: 10px; }"
            )
            for tab_name in tab_order:
                if tab_name not in active_tabs:
                    continue
                page = QWidget()
                flayout = QFormLayout(page)
                flayout.setSpacing(8)
                flayout.setContentsMargins(8, 8, 8, 8)
                for field in active_tabs[tab_name]:
                    w = self._create_field_widget(
                        field, values.get(field.name))
                    if w:
                        flayout.addRow(f"{field.label}:", w)
                flayout.addItem(QSpacerItem(
                    0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))
                tabs.addTab(page, tab_name)
            outer.addWidget(tabs, 1)

        # ── Wygładzanie (na samym końcu, pod zakładkami) ───────────
        smooth_row = QWidget()
        smooth_hbox = QHBoxLayout(smooth_row)
        smooth_hbox.setContentsMargins(0, 6, 0, 2)
        smooth_label = QLabel("Wygładzanie:")
        smooth_label.setStyleSheet("font-size: 10px; color: #aaa;")
        self._smoothing_spin = QSpinBox()
        self._smoothing_spin.setRange(0, 20)
        self._smoothing_spin.setValue(int(values.get("smoothing", 0)))
        self._smoothing_spin.setSuffix(" okno")
        self._smoothing_spin.setToolTip(
            "0 = brak wygładzania\n20 = maksymalne wygładzenie"
        )
        self._smoothing_spin.valueChanged.connect(
            lambda v: self._emit_change("smoothing", v)
        )
        smooth_hbox.addWidget(smooth_label)
        smooth_hbox.addWidget(self._smoothing_spin, 1)
        outer.addWidget(smooth_row)

        outer.addItem(QSpacerItem(
            0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

    def _create_field_widget(
        self, field: FieldSchema, value: Any,
    ) -> QWidget | None:
        """Tworzy widget dla pojedynczego pola schematu."""
        name = field.name

        if field.field_type == "bool":
            cb = QCheckBox()
            cb.setChecked(bool(value))
            cb.toggled.connect(
                lambda checked, n=name: self._emit_change(n, checked)
            )
            return cb

        if field.field_type == "choice":
            cmb = QComboBox()
            if field.choices:
                cmb.addItems([str(c) for c in field.choices])
            if value is not None:
                cmb.setCurrentText(str(value))
            cmb.currentTextChanged.connect(
                lambda txt, n=name: self._emit_change(n, txt)
            )
            return cmb

        if field.field_type == "int":
            spin = QSpinBox()
            if field.min_val is not None and field.max_val is not None:
                spin.setRange(int(field.min_val), int(field.max_val))
            else:
                spin.setRange(-9999, 99999)
            if value is not None:
                try:
                    spin.setValue(int(value))
                except (ValueError, TypeError):
                    spin.setValue(0)
            spin.valueChanged.connect(
                lambda v, n=name: self._emit_change(n, v)
            )
            return spin

        if field.field_type == "float":
            spin = QDoubleSpinBox()
            if field.min_val is not None and field.max_val is not None:
                spin.setRange(float(field.min_val), float(field.max_val))
            else:
                spin.setRange(-9999.0, 99999.0)
            spin.setSingleStep(field.step or 0.001)
            spin.setDecimals(4)
            if value is not None:
                try:
                    spin.setValue(float(value))
                except (ValueError, TypeError):
                    spin.setValue(0.0)
            spin.valueChanged.connect(
                lambda v, n=name: self._emit_change(n, v)
            )
            return spin

        if field.field_type == "text":
            edit = QLineEdit(str(value) if value is not None else "")
            edit.textChanged.connect(
                lambda txt, n=name: self._emit_change(n, txt)
            )
            return edit

        if field.field_type == "color":
            row = QWidget()
            hbox = QHBoxLayout(row)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(4)

            current_color = str(value) if value else "#FFFFFF"
            edit = QLineEdit(current_color)
            edit.setMaximumWidth(90)
            edit.textChanged.connect(
                lambda txt, n=name: self._emit_change(n, txt)
            )
            hbox.addWidget(edit)

            # Podgląd koloru
            color_swatch = QLabel()
            color_swatch.setFixedSize(24, 24)
            color_swatch.setStyleSheet(
                f"background-color: {current_color}; "
                f"border: 1px solid #555; border-radius: 2px;"
            )
            hbox.addWidget(color_swatch)

            btn = QPushButton("...")
            btn.setFixedWidth(30)
            btn.clicked.connect(
                lambda checked=False, e=edit, s=color_swatch:
                self._pick_color(e, s)
            )
            hbox.addWidget(btn)
            hbox.addStretch()

            return row

        return None

    def _pick_color(self, edit: QLineEdit, swatch: QLabel) -> None:
        color = QColorDialog.getColor()
        if color.isValid():
            color_name = color.name()
            edit.setText(color_name)
            swatch.setStyleSheet(
                f"background-color: {color_name}; "
                f"border: 1px solid #555; border-radius: 2px;"
            )

    def _emit_change(self, field_name: str, value: Any) -> None:
        """Emituje sygnał zmiany właściwości."""
        if self._current_key and not self._suppress_emit:
            self.signals.sig_property_changed.emit(
                self._current_key, field_name, value,
            )
