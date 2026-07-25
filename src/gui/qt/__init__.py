"""Pakiet GUI PySide6 dla TeleMGP.

Struktura:
- application.py  — QApplication + entry point main()
- main_window.py  — QMainWindow z QTabWidget
- signals.py      — wszystkie sygnały Qt (GUI ↔ kontroler)
- models.py       — modele danych (DataStream, FieldSchema)
- controller.py   — AppController — most między GUI a logiką biznesową
- tabs/           — zakładki głównego okna
- widgets/        — widgety wielokrotnego użytku
- property_pages/ — strony właściwości (QStackedWidget)
"""
