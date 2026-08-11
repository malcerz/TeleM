"""Konfiguracja pytest – pomijanie legacy testów Tkinter.

test_fit_registration.py i test_widgets.py zostały napisane dla starszego
interfejsu Tkinter (src.gui.hud_tuner_app, src.gui.widgets).
GUI zostało przepisane na PySide6; tamte moduły już nie istnieją.
Pliki testów zachowane jako archiwum (wraz z .bak).
"""

collect_ignore = [
    "test_fit_registration.py",
    "test_widgets.py",
]
