"""Entry point aplikacji PySide6."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.gui.qt.signals import get_signals


def main() -> None:
    """Główny entry point aplikacji TeleMGP (PySide6)."""
    app = QApplication(sys.argv)
    app.setApplicationName("TeleMGP")

    # Inicjalizacja kontrolera (most GUI ↔ logika biznesowa)
    _controller = AppController()  # noqa: F841

    # Główne okno – pełny ekran
    window = MainWindow()
    window.showMaximized()

    # ── Tryb testowy: python TeleMGP0.py -test ──────────────────────────
    if "-test" in sys.argv:
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        video_dir = base_dir / "video"
        video_path = video_dir / "GL010032.mp4"
        fit_path = video_dir / "Morning_Ride.fit"

        if video_path.exists() and fit_path.exists():
            QTimer.singleShot(500, lambda: get_signals().sig_files_selected.emit(
                [str(video_path)], "", str(fit_path),
            ))
        else:
            print("[test] Brak plików testowych:", flush=True)
            if not video_path.exists():
                print(f"  MP4: {video_path} — nie znaleziono", flush=True)
            if not fit_path.exists():
                print(f"  FIT: {fit_path} — nie znaleziono", flush=True)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
