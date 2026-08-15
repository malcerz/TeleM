"""Pomiar rozmiaru współdzielonego podglądu w zakładkach Projekt i Rendering."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from src.gui.qt.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    app.processEvents()

    def report(label):
        pv = win.preview
        print(f"{label}:")
        print(f"  VideoPreview  : {pv.width()} x {pv.height()}")
        print(f"  image_label   : {pv.image_label.width()} x {pv.image_label.height()}")
        slot = win._project_tab.preview_slot if label.startswith("Projekt") else win._render_tab.preview_slot
        print(f"  preview_slot  : {slot.width()} x {slot.height()}")
        print(f"  tab           : {win.tabs.currentWidget().width()} x {win.tabs.currentWidget().height()}")

    win.tabs.setCurrentWidget(win._project_tab)
    app.processEvents()
    report("Projekt")

    win.tabs.setCurrentWidget(win._render_tab)
    app.processEvents()
    report("Rendering")

    # przy mniejszym oknie
    win.resize(1200, 800)
    app.processEvents()
    win.tabs.setCurrentWidget(win._project_tab)
    app.processEvents()
    report("Projekt (1200x800)")
    win.tabs.setCurrentWidget(win._render_tab)
    app.processEvents()
    report("Rendering (1200x800)")

    win.close()
    app.processEvents()
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
