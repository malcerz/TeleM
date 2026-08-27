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
    _controller = AppController()
    window = MainWindow()
    window.set_controller(_controller)  # wiąże współdzielony podgląd (jeden raz)
    app.aboutToQuit.connect(_controller.cancel_render_and_wait)
    window.showMaximized()

    # Zgłoś błąd, jeśli brak bibliotek libmpv (podgląd GPU MPV niedostępny)
    window.check_mpv_availability()

    # ── Tryb testowy: python TeleMGP.py -test / --test ──────────────────
    if "-test" in sys.argv or "--test" in sys.argv:
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        video_dir = base_dir / "Video"
        if not video_dir.exists():
            video_dir = base_dir / "video"

        video_path = video_dir / "GX020079.mp4"
        if not video_path.exists():
            video_path = video_dir / "GL010032.mp4"

        fit_path = video_dir / "Morning_Ride.fit"

        if video_path.exists() and fit_path.exists():
            print(f"[TEST MODE] Wczytywanie plików testowych:\n  MP4: {video_path}\n  FIT: {fit_path}", flush=True)
            QTimer.singleShot(500, lambda: get_signals().sig_files_selected.emit(
                [str(video_path)], "", str(fit_path),
            ))
        else:
            print("[TEST MODE] Brak plików testowych:", flush=True)
            if not video_path.exists():
                print(f"  MP4: {video_path} — nie znaleziono", flush=True)
            if not fit_path.exists():
                print(f"  FIT: {fit_path} — nie znaleziono", flush=True)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
