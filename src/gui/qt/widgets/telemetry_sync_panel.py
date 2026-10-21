"""SYNCHRONIZACJA TELEMETRII — panel w prawym panelu zakładki Projekt.

Widoczny, gdy nie jest zaznaczony żaden wskaźnik.  Wyłącznie emituje sygnały;
logika (kontrakt offsetu, SmartSync, zapis) jest w kontrolerze (SyncMixin).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from src.gui.qt.signals import get_signals

_LEVEL_LABELS = {"high": "wysoka", "medium": "średnia", "low": "niska", "none": "brak"}


class TelemetrySyncPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._suppress = False
        self._busy = False
        self._build_ui()
        self.signals.sig_sync_state_changed.connect(self.on_state)
        self.signals.sig_sync_progress.connect(self.on_progress)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(6)

        title = QLabel("<b>SYNCHRONIZACJA TELEMETRII</b>")
        title.setStyleSheet(
            "color: #79c0ff; font-size: 10px; font-weight: bold; "
            "padding-bottom: 2px; border-bottom: 1px solid #333;"
        )
        root.addWidget(title)

        row = QHBoxLayout()
        row.addWidget(QLabel("Przesunięcie:"))
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(2)
        self.spin.setRange(-86400.0, 86400.0)
        self.spin.setSingleStep(0.01)
        self.spin.setSuffix(" s")
        self.spin.setKeyboardTracking(False)
        self.spin.setToolTip(
            "czas telemetrii = start wideo + pozycja w wideo + przesunięcie\n"
            "Dodatnia wartość: wskaźniki pokazują dane z późniejszej chwili aktywności."
        )
        self.spin.valueChanged.connect(self._on_spin)
        row.addWidget(self.spin, 1)
        root.addLayout(row)

        grid = QGridLayout()
        grid.setSpacing(4)
        for col, (label, delta) in enumerate((("−1 s", -1.0), ("−0,1 s", -0.1), ("+0,1 s", 0.1), ("+1 s", 1.0))):
            btn = QPushButton(label)
            btn.setToolTip(f"Przesuń telemetrię o {delta:+.1f} s")
            btn.clicked.connect(lambda _=False, d=delta: self.signals.sig_sync_offset_nudge.emit(d))
            grid.addWidget(btn, 0, col)
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setToolTip("Przywróć czas z plików (przesunięcie 0)")
        self.btn_reset.clicked.connect(self.signals.sig_sync_offset_reset.emit)
        grid.addWidget(self.btn_reset, 1, 0, 1, 2)
        self.btn_auto = QPushButton("Auto synchronizacja")
        self.btn_auto.setToolTip(
            "SmartSync: ślad GPS kamery (GoPro) albo korelacja IMU kamery z FIT/GPX (DJI, kamera bez GPS)."
        )
        self.btn_auto.clicked.connect(self._on_auto_clicked)
        grid.addWidget(self.btn_auto, 1, 2, 1, 2)
        root.addLayout(grid)

        self.btn_accept = QPushButton("Zastosuj propozycję")
        self.btn_accept.setVisible(False)
        self.btn_accept.clicked.connect(self.signals.sig_sync_proposal_accept.emit)
        root.addWidget(self.btn_accept)

        self.info = QLabel("Źródło: brak korekty")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.setStyleSheet("color: #aaa; font-size: 10px;")
        root.addWidget(self.info)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #ccc; font-size: 10px;")
        root.addWidget(self.status)

    # ── GUI → kontroler ────────────────────────────────────────────────
    def _on_spin(self, value: float) -> None:
        if not self._suppress:
            self.signals.sig_sync_offset_set.emit(float(value))

    def _on_auto_clicked(self) -> None:
        if self._busy:
            self.signals.sig_sync_auto_cancel.emit()
        else:
            self.signals.sig_sync_auto_requested.emit()

    def focus_offset(self) -> None:
        """Fokus na „Przesunięcie” gotowe do wpisania; wartość bez zmian."""
        self.spin.setFocus(Qt.MouseFocusReason)
        self.spin.selectAll()

    # ── kontroler → GUI ────────────────────────────────────────────────
    def on_progress(self, text: str) -> None:
        self.status.setText(text)

    def on_state(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._suppress = True
        try:
            self.spin.setValue(float(payload.get("offset_s", 0.0)))
        finally:
            self._suppress = False
        self._busy = bool(payload.get("busy"))
        self.btn_auto.setText("Anuluj analizę" if self._busy else "Auto synchronizacja")
        self.btn_auto.setEnabled(bool(payload.get("has_activity")) or self._busy)

        parts = [f"Źródło: {payload.get('method_label', '')}"]
        level = payload.get("confidence_level")
        conf = payload.get("confidence")
        if level:
            pct = f" ({float(conf):.0%})" if isinstance(conf, (int, float)) else ""
            parts.append(f"Wiarygodność: {_LEVEL_LABELS.get(level, level)}{pct}")
        clips = payload.get("clip_offsets_s") or {}
        if clips:
            per = ", ".join(f"klip {int(k) + 1}: {float(payload['offset_s']) + float(v):+.2f} s"
                            for k, v in sorted(clips.items()))
            parts.append(f"Korekty per klip: {per}")
        if not payload.get("has_activity"):
            parts.append("Brak FIT/GPX — nie ma czego synchronizować.")
        self.info.setText("\n".join(parts))

        prop = payload.get("proposal")
        if prop and prop.get("offset_s") is not None and not self._busy:
            self.btn_accept.setText(f"Zastosuj propozycję {float(prop['offset_s']):+.2f} s")
            self.btn_accept.setVisible(True)
        else:
            self.btn_accept.setVisible(False)
        if self._busy:
            self.status.setText(payload.get("message") or "SmartSync: analiza...")
        else:
            self.status.setText(payload.get("message") or "")
