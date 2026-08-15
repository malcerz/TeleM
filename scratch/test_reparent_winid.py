"""Test: czy reparenting VideoPreview między kontenerami zachowuje stabilne winId.

Kluczowe pytanie architektoniczne: czy można przenosić POJEDYNCZY widget
VideoPreview (z natywnym oknem MPV) między zakładkami Projekt ↔ Rendering
bez utraty wiązania MPV (wid) i bez ponownej inicjalizacji backendu.

Uruchomienie:  python scratch/test_reparent_winid.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Ustaw PATH dla libmpv (tak jak robi to playback_mixin)
os.environ["PATH"] = str(BASE) + os.pathsep + os.environ.get("PATH", "")
if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(str(BASE))
    except Exception:
        pass

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import QTimer

try:
    import mpv
    MPV_OK = True
except Exception as e:
    MPV_OK = False
    print(f"mpv import failed: {e}")


def main() -> int:
    app = QApplication(sys.argv)

    # Dwa kontenery symulujące strony zakładek
    container_a = QWidget()
    container_a.setWindowTitle("Projekt (A)")
    container_a.resize(600, 400)
    lay_a = QVBoxLayout(container_a)
    container_a.show()

    container_b = QWidget()
    container_b.setWindowTitle("Rendering (B)")
    container_b.resize(600, 400)
    lay_b = QVBoxLayout(container_b)

    # Widget z natywnym oknem (odpowiednik mpv_widget z VideoPreview)
    from PySide6.QtCore import Qt
    holder = QWidget()
    holder.setAttribute(Qt.WA_NativeWindow, True)
    holder.setAttribute(Qt.WA_DontCreateNativeAncestors, True)

    label = QLabel("VIDEO SURFACE")
    v = QVBoxLayout(holder)
    v.addWidget(label)

    lay_a.addWidget(holder)
    container_a.show()

    def get_id():
        return int(holder.winId())

    app.processEvents()
    id1 = get_id()
    print(f"winId w kontenerze A: {id1}")

    # Reparent do kontenera B
    holder.setParent(container_b)
    lay_b.addWidget(holder)
    container_b.show()
    app.processEvents()
    id2 = get_id()
    print(f"winId w kontenerze B: {id2}")

    # Reparent z powrotem do A
    holder.setParent(container_a)
    lay_a.addWidget(holder)
    container_a.show()
    app.processEvents()
    id3 = get_id()
    print(f"winId z powrotem w A: {id3}")

    print("=== WYNIK ===")
    stable = (id1 == id2 == id3)
    print(f"winId stabilne: {stable}")
    print(f"mpv import OK: {MPV_OK}")

    QTimer.singleShot(500, app.quit)
    app.exec()
    return 0 if stable else 1


if __name__ == "__main__":
    sys.exit(main())
