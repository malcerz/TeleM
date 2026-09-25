"""Konfiguracja pytest – pomijanie legacy testów Tkinter.

test_fit_registration.py i test_widgets.py zostały napisane dla starszego
interfejsu Tkinter (src.gui.hud_tuner_app, src.gui.widgets).
GUI zostało przepisane na PySide6; tamte moduły już nie istnieją.
Pliki testów zachowane jako archiwum (wraz z .bak).
"""
import os
from pathlib import Path

ff_bin = Path(r"C:\_Dev\BikeRideHUD-intel\third_party\ffmpeg-9.0.1-full_build-shared\bin")
if ff_bin.exists() and hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(str(ff_bin))
    except Exception:
        pass

collect_ignore = [
    "test_fit_registration.py",
    "test_widgets.py",
]
