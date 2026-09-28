# RAPORT: Naprawa regresji składniowej startupu UI (render_mixin.py)

**DATA:** 2026-09-24  
**BACKEND:** AMD (AMD_NATIVE_D3D11) / GUI  

---

## 1. Wymagane pola diagnostyczne

```text
SYNTAX_ROOT_CAUSE=Podwójna klauzula 'else:' w metodzie _render_pipeline w pliku src/gui/qt/_mixins/render_mixin.py (linie 1103 i 1112), wywołana automatycznym patchem w scratch/patch_render_mixin.py z poprzedniego etapu UI, który powtórzył 'else: stream_overlay_to_ffmpeg' oraz wkleił logikę wyciągania stats poza blokiem 'if amd_child_enabled:'.
BROKEN_FILE=src/gui/qt/_mixins/render_mixin.py
BROKEN_LINE=1112
LAST_UI_CHANGE_CAUSED_REGRESSION=TAK (wdrożenie zwracania słownika stats dla popupu pojedynczego eksportu)

PY_COMPILE_RENDER_MIXIN=PASS
PY_COMPILE_ALL_CHANGED=PASS
APPLICATION_IMPORT=PASS
MAIN_WINDOW_OPENED=True
STARTUP_TRACEBACK=False

QUEUE_UI_SMOKE=PASS
PROPERTY_EDITOR_SMOKE=PASS
PREVIEW_SMOKE=PASS

8K_CODE_CHANGED=NO
ROTATION_CODE_CHANGED=NO
NVIDIA_FILES_CHANGED=0
INTEL_FILES_CHANGED=0

MODIFIED_FILES=src/gui/qt/_mixins/render_mixin.py
CASE=CASE A — syntax fixed, import PASS, real GUI startup PASS
```

---

## 2. Diagnoza (Audyt)

Podczas poprzedniego etapu UI wdrożono zbieranie statystyk wydajności (`render_fps`, `avg_qp`) dla okna popup zakończenia eksportu. W tym celu utworzono skrypt pomocniczy `scratch/patch_render_mixin.py`, który zastąpił instrukcję `return {"total_overlay_frames": 0, "png_duration": 0}` blokiem zawierającym dodatkowe `else: stream_overlay_to_ffmpeg(**stream_kwargs)`.

W pliku `src/gui/qt/_mixins/render_mixin.py` istniała już wcześniej klauzula `else:` (linia 1103). Po wklejeniu powstała struktura:
```python
        if amd_child_enabled:
            ...
            stats = run_amd_render_child(...)
        else:
            stream_overlay_to_ffmpeg(**stream_kwargs)

            if 'stats' in locals() and isinstance(stats, dict) and "result" in stats:
                ...
        else:
            stream_overlay_to_ffmpeg(**stream_kwargs)
```
Python zgłosił błąd krytyczny przy imporcie:
`File "src\gui\qt\_mixins\render_mixin.py", line 1112: else: SyntaxError: invalid syntax`

---

## 3. Zastosowana naprawa

Usunięto zduplikowany blok `else:` oraz umieszczono poprawną logikę wyciągania i zwracania `stats` bezpośrednio wewnątrz gałęzi `if amd_child_enabled:`, zachowując domyślny fallback dla ścieżki alternatywnej:

```python
        if amd_child_enabled:
            ...
            stats = run_amd_render_child(...)
            if isinstance(stats, dict) and "result" in stats and isinstance(stats["result"], dict):
                return stats["result"]
            if isinstance(stats, dict) and stats:
                return stats
        else:
            stream_overlay_to_ffmpeg(**stream_kwargs)

        return {"total_overlay_frames": 0, "png_duration": 0}
```

Semantyka popupu (brak per-job popupu dla kolejki, pełne statystyki w pojedynczym eksporcie) została w 100% zachowana bez ingerencji w mechanizm kolejki czy renderery GPU.

---

## 4. Weryfikacja

1. **py_compile check:**
   - `src/gui/qt/_mixins/render_mixin.py`: PASS
   - `src/gui/qt/tabs/render_tab.py`: PASS
   - `src/gui/export_queue.py`: PASS
   - `src/indicators/moving_map.py`: PASS
   - `src/gui/qt/models.py`: PASS
   - `src/gui/qt/widgets/property_editor.py`: PASS
   - `src/indicators/chart.py`: PASS
   - `PY_COMPILE_ALL_CHANGED=PASS`

2. **Application Import Check:**
   - Wywołanie: `python -c "from src.gui.qt.application import main; print('APPLICATION_IMPORT_OK')"`
   - Wynik: `APPLICATION_IMPORT_OK`

3. **Real GUI Startup & Smoke Tests:**
   - Uruchomienie pełnego okna aplikacji PySide6 na platformie `windows`.
   - `MAIN_WINDOW_OPENED=True`
   - `STARTUP_TRACEBACK=False`
   - Otwarcie panelu kolejki (`RenderTab`): 19 istniejących zadań wczytanych poprawnie (`QUEUE_UI_SMOKE=PASS`).
   - Multi-selection w `queue_list` przetestowane pomyślnie bez wyjątków.
   - Otwarcie `PropertyEditor` (`ProjectTab`) i konfiguracja wskaźnika: PASS (`PROPERTY_EDITOR_SMOKE=PASS`).
   - Podgląd i silnik MPV (D3D11VA GPU): PASS (`PREVIEW_SMOKE=PASS`).
   - Czyste zamknięcie procesu (`closeEvent`): PASS.

---

## 5. Podsumowanie i status

- Zmiany ograniczone wyłącznie do usunięcia błędu składniowego w `src/gui/qt/_mixins/render_mixin.py`.
- Żadne pliki NVIDIA/Intel/8K/rendererów GPU nie zostały naruszone.
- Status etapu: **COMPLETE** (CASE A).
