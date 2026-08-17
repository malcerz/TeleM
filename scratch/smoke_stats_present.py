"""Smoke test prezentacji statystyk/paska (offscreen) — bez eksportu."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui.qt.tabs.render_tab import RenderTab  # noqa: E402

app = QApplication([])
tab = RenderTab()
tab.resize(1200, 800)
tab.show()
app.processEvents()

# ── dwa kolejne update'y → geometria ma być stabilna ─────────────────
tab._set_stats(645, 1131, 18.0, 34.2, "Renderowanie...")
t1 = tab.lbl_stats.text()
h1, w1 = tab.lbl_stats.height(), tab.lbl_stats.width()
tab._set_stats(850, 1131, 24.0, 35.0, "Renderowanie...")
t2 = tab.lbl_stats.text()
h2, w2 = tab.lbl_stats.height(), tab.lbl_stats.width()

print("TEXT1:", repr(t1))
print("TEXT2:", repr(t2))
print("single_line:", ("\n" not in t1) and ("\n" not in t2))
print("wordWrap:", tab.lbl_stats.wordWrap())
print("align:", int(tab.lbl_stats.alignment()))
print("geom_stable_h:", h1 == h2, (h1, h2))
print("geom_stable_w:", w1 == w2, (w1, w2))
print("color_black:", "color: black" in tab.lbl_stats.styleSheet().lower())
print("progress_min_height:", tab.progress.minimumHeight(), ">=8:",
      tab.progress.minimumHeight() >= 8)

# ── pełna ścieżka zdarzenia progress (jak z eksportera) ──────────────
tab._rendering = True
tab._render_total = 1131
tab._on_render_progress(300, 1131, 9.0, 33.3, None)
print("via_on_render_progress:", repr(tab.lbl_stats.text()))
print("progress_value:", tab.progress.value())

# finalizacja: cap 99, status Finalizacja...
tab._on_render_progress(1131, 1131, 31.7, 35.7, None)
print("finalization:", repr(tab.lbl_stats.text()), "progress:", tab.progress.value())

# czarny kolor również w finalnym renderowania path (setText nie resetuje)
print("OK_ALL" if ("\n" not in tab.lbl_stats.text()) else "MULTILINE_FOUND")
