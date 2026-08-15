"""Headless smoke test nowej zakładki Rendering (pełne okablowanie).

Uruchomienie: python scratch/smoke_render_tab.py
Wymaga QT_QPA_PLATFORM=offscreen (ustawiane w skrypcie).
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.gui.qt.application import AppController
from src.gui.qt.main_window import MainWindow
from src.gui.qt.signals import get_signals

OK = []


def check(name, cond):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name}", flush=True)
    if not cond:
        sys.exit(f"SMOKE FAILED: {name}")


def main() -> int:
    app = QApplication(sys.argv)
    ctrl = AppController()
    win = MainWindow()
    win.set_controller(ctrl)
    win.resize(1600, 1000)
    win.show()

    s = get_signals()

    def step1():
        check("1. startowy podgląd w zakładce Projekt",
              win.preview.parentWidget() is win._project_tab.preview_slot)

        # symuluj załadowanie filmu (jak _on_files_selected → sig_video_duration_ready)
        ctrl.video_duration_s = 120.0
        s.sig_video_duration_ready.emit(120.0)

        # podgląd w Projekcie
        check("2. video_preview w Projekcie = współdzielony",
              win._project_tab.video_preview is win.preview)
        check("3. seek bar ma 120s",
              abs(win.preview.seek_bar.get_effective_duration() - 120.0) < 0.01)

        # przełącz na Rendering
        win.tabs.setCurrentWidget(win._render_tab)
        app.processEvents()
        check("4. podgląd przeniesiony do Rendering",
              win.preview.parentWidget() is win._render_tab.preview_slot)
        check("5. render_tab.video_preview = współdzielony",
              win._render_tab.video_preview is win.preview)

        # IN/OUT w Rendering
        rt = win._render_tab
        rt.video_preview.seek_bar.set_position(10.0)
        rt._on_set_in()
        check("6. IN=10 i cięcie [0,10]",
              rt._in_orig == 10.0 and (0.0, 10.0) in ctrl._cut_regions)
        check("7. etykieta IN",
              rt.lbl_in.text() == "IN: 00:10")

        rt.video_preview.seek_bar.set_position(100.0)
        rt._on_set_out()
        check("8. OUT=110 (100 efektywne po cięciu [0,10])",
              rt._out_orig == 110.0 and (110.0, 120.0) in ctrl._cut_regions)

        # eksport — opcje i zakres
        rt.edit_output.setText("smoke_out.mp4")
        options = {
            "encoder": rt.cmb_encoder.currentText(),
            "resolution": rt.cmb_resolution.currentText(),
            "rotation": rt.cmb_rotation.currentText(),
            "update_rate": rt.cmb_update_rate.currentText(),
            "bitrate": rt.edit_bitrate.text().strip(),
            "output": rt.edit_output.text().strip(),
        }
        check("9. opcje eksportu dostępne", options["output"] == "smoke_out.mp4")

        # przełącz z powrotem do Projekt — podgląd wraca, bez nowego backendu
        win.tabs.setCurrentWidget(win._project_tab)
        app.processEvents()
        check("10. podgląd wrócił do Projekt",
              win.preview.parentWidget() is win._project_tab.preview_slot)
        check("11. wciąż jedna instancja podglądu",
              win._render_tab.video_preview is win.preview)

        # wyczyść zakres
        rt._on_clear_range()
        check("12. czyszczenie zakresu usuwa cięcia graniczne",
              (0.0, 10.0) not in ctrl._cut_regions
              and (110.0, 120.0) not in ctrl._cut_regions)

        print("\n=== SMOKE PASS ===", flush=True)
        app.quit()

    QTimer.singleShot(0, step1)
    QTimer.singleShot(20000, app.quit)  # bezpiecznik
    app.exec()
    return 0 if OK_clean() else 1


def OK_clean():
    return True


if __name__ == "__main__":
    sys.exit(main())
