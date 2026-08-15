"""Sprawdza, czy podział 75/25 w zakładce Rendering faktycznie się renderuje."""

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

    # przełącz na Rendering
    win.tabs.setCurrentWidget(win._render_tab)
    app.processEvents()

    rt = win._render_tab

    print(f"okno: {win.width()}x{win.height()}")
    print(f"Rendering tab: {rt.width()}x{rt.height()}")

    lw = rt.left_panel.width()
    rw = rt.right_panel.width()
    total = lw + rw
    print(f"lewy panel: {lw}px, prawy panel: {rw}px, razem: {total}px")
    ratio = lw / total * 100.0 if total else 0.0
    print(f"lewy udział: {ratio:.1f}%  (oczekiwane ~75%)")

    # Sprawdź podgląd w slocie
    slot = rt.preview_slot
    preview = win.preview
    print(f"preview_slot: {slot.width()}x{slot.height()}")
    print(f"preview (VideoPreview): {preview.width()}x{preview.height()}")
    print(f"preview parent = render slot? {preview.parentWidget() is slot}")

    ok = 70.0 <= ratio <= 80.0 and preview.parentWidget() is slot
    print("=== SPLIT OK ===" if ok else "=== SPLIT FAIL ===")
    win.close()
    app.processEvents()
    app.quit()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
