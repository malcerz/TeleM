"""Benchmark dokładnego czasu ładowania projektu GX010361.MP4 według etapów z v1.14:
1. Kliknięcie Wczytaj -> rozpoczęcie operacji (kickoff / return _on_load)
2. Kliknięcie Wczytaj -> dane telemetrii gotowe (GPMF / candidate range / streams)
3. Kliknięcie Wczytaj -> pierwsza klatka podglądu (preview frame extraction)
4. Kliknięcie Wczytaj -> projekt gotowy (100% postępu, HUD composite ready)
Zarówno dla zimnego (cold cache) jak i ciepłego (warm cache).
"""

import os
import sys
import time
import shutil
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer

from src.gui.qt.controller import AppController
from src.gui.qt.tabs.load_tab import LoadTab
from src.telemetry_cache_manager import get_media_cache_dir
from src.telemetry_native_gpmf import _IN_MEMORY_LIGHT_CACHE

VIDEO_PATH = "F:/GoPro/2026-10-09/GX010361.MP4"


def run_single_load_benchmark(warm: bool = False) -> dict:
    app = QApplication.instance() or QApplication([])

    video_path_obj = Path(VIDEO_PATH)
    if not video_path_obj.exists():
        raise FileNotFoundError(f"Video file not found: {VIDEO_PATH}")

    media_cache_dir = get_media_cache_dir(VIDEO_PATH)

    if not warm:
        # Zimny cache: wyczyść pamięć i dysk
        _IN_MEMORY_LIGHT_CACHE.clear()
        if media_cache_dir.exists():
            shutil.rmtree(media_cache_dir, ignore_errors=True)
    else:
        # Ciepły cache: upewnij się, że dysk ma cache
        pass

    ctrl = AppController()
    tab = LoadTab()

    # Połącz sygnały tak jak w głównej aplikacji
    tab.signals.sig_files_selected.connect(ctrl._on_files_selected)
    tab.signals.sig_late_telemetry_matched.connect(ctrl.late_attach_telemetry)

    loop = QEventLoop()

    times = {
        "t_click": 0.0,
        "t_kickoff": 0.0,
        "t_telem_ready": 0.0,
        "t_first_frame": 0.0,
        "t_project_ready": 0.0,
    }

    def on_progress(pct: int, msg: str):
        now = time.perf_counter()
        if pct == 75 and times["t_telem_ready"] == 0.0:
            times["t_telem_ready"] = now
        elif pct == 90 and times["t_first_frame"] == 0.0:
            times["t_first_frame"] = now
        elif pct >= 100 and times["t_project_ready"] == 0.0:
            times["t_project_ready"] = now
            loop.quit()

    ctrl.signals.sig_progress.connect(on_progress)

    # Ustaw ścieżkę wideo w LoadTab
    tab.set_video_paths([VIDEO_PATH], start_search=False)

    # Bezpiecznik timeoutu (np. max 15 sekund)
    timeout_timer = QTimer()
    timeout_timer.setSingleShot(True)
    timeout_timer.timeout.connect(loop.quit)
    timeout_timer.start(60000)

    # Pomiar kliknięcia "Wczytaj"
    times["t_click"] = time.perf_counter()
    tab._on_load()
    times["t_kickoff"] = time.perf_counter()

    loop.exec()

    # Allow worker thread and events to finalize cleanly
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()

    t_click = times["t_click"]
    dt_kickoff = (times["t_kickoff"] - t_click) * 1000.0
    dt_telem = (times["t_telem_ready"] - t_click) * 1000.0 if times["t_telem_ready"] > 0 else 0.0
    dt_frame = (times["t_first_frame"] - t_click) * 1000.0 if times["t_first_frame"] > 0 else 0.0
    dt_ready = (times["t_project_ready"] - t_click) * 1000.0 if times["t_project_ready"] > 0 else 0.0

    tab.close()

    return {
        "kickoff_ms": dt_kickoff,
        "telemetry_ready_ms": dt_telem,
        "first_frame_ms": dt_frame,
        "project_ready_ms": dt_ready,
    }


def main():
    print(f"Rozpoczynam benchmark na pliku: {VIDEO_PATH}")

    # 1. Zimny cache
    print("\n--- POMIAR: ZIMNY CACHE (Cold Cache) ---")
    cold_results = run_single_load_benchmark(warm=False)
    print(f"  1. Klikniecie Wczytaj -> rozpoczecie operacji: {cold_results['kickoff_ms']:.2f} ms")
    print(f"  2. Klikniecie Wczytaj -> dane telemetrii gotowe: {cold_results['telemetry_ready_ms']:.2f} ms")
    print(f"  3. Klikniecie Wczytaj -> pierwsza klatka podgladu: {cold_results['first_frame_ms']:.2f} ms")
    print(f"  4. Klikniecie Wczytaj -> projekt gotowy:         {cold_results['project_ready_ms']:.2f} ms")

    # 2. Ciepły cache
    print("\n--- POMIAR: CIEPŁY CACHE (Warm Cache) ---")
    warm_results = run_single_load_benchmark(warm=True)
    print(f"  1. Klikniecie Wczytaj -> rozpoczecie operacji: {warm_results['kickoff_ms']:.2f} ms")
    print(f"  2. Klikniecie Wczytaj -> dane telemetrii gotowe: {warm_results['telemetry_ready_ms']:.2f} ms")
    print(f"  3. Klikniecie Wczytaj -> pierwsza klatka podgladu: {warm_results['first_frame_ms']:.2f} ms")
    print(f"  4. Klikniecie Wczytaj -> projekt gotowy:         {warm_results['project_ready_ms']:.2f} ms")


if __name__ == "__main__":
    main()
