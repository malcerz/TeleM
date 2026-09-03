# RAPORT: GUI v4 — Fullscreen Lifecycle & Next Frame Step

## 1. TASK
Naprawa dwóch krytycznych defektów zidentyfikowanych w teście użytkownika:
1. **NEXT FRAME**: Przycisk Next Frame nie przesuwał obrazu do przodu w podglądzie wideo (podczas gdy Previous Frame działał).
2. **FULLSCREEN EXIT / QT WIDGET LIFECYCLE**: Wyjście z trybu pełnoekranowego (ESC) kończyło się błędem:
   `RuntimeError: libshiboken: Internal C++ object (PySide6.QtWidgets.QTabWidget) already deleted.`

---

## 2. ROOT CAUSE: DELETED QTabWidget

### Diagnostyka ownership w Qt / QMainWindow
- W bibliotece Qt metoda `QMainWindow.setCentralWidget(new_widget)` przejmuje wyłączną własność (`ownership`) przekazywanego wskaźnika widgetu.
- Jeśli przed jej wywołaniem w oknie istniał już inny `centralWidget` (w naszym przypadku `self.tabs`), Qt automatycznie niszczy i zwalnia z pamięci C++ poprzedni obiekt widgetu.
- Poprzednia implementacja wykonywała:
  ```python
  self.setCentralWidget(self.preview)
  ```
  W tym momencie obiekt bazowy C++ powiązany z `self.tabs` został bezpowrotnie usunięty przez Qt.
- Przy próbie wyjścia z pełnego ekranu:
  ```python
  self.setCentralWidget(self.tabs)
  ```
  Pythonowy wrapper `self.tabs` próbował odwołać się do zniszczonego obiektu C++, rzucając wyjątek `RuntimeError: libshiboken: Internal C++ object (PySide6.QtWidgets.QTabWidget) already deleted`.

### Rozwiązanie: `takeCentralWidget()`
- Użyto metody `QMainWindow.takeCentralWidget()`, która zdejmuje centralny widget z hierarchii okna i przekazuje pełne prawo własności z powrotem do środowiska Pythona, **nie niszcząc obiektu C++**.
- Przy wejściu do fullscreen:
  ```python
  normal_central = self.takeCentralWidget()
  self._fullscreen_saved_central = normal_central  # silna referencja w Pythonie
  normal_central.hide()
  self.setCentralWidget(self.preview)
  ```
- Przy wyjściu z fullscreen:
  ```python
  preview = self.takeCentralWidget()  # zapobiega usunięciu VideoPreview przez Qt
  self.setCentralWidget(self._fullscreen_saved_central)
  self._fullscreen_saved_central.show()
  self._fullscreen_saved_central = None
  self._move_preview_to(target_slot)
  ```
- Dzięki temu oba obiekty C++ (`self.tabs` i `self.preview`) zachowują ciągłość życia (`shiboken6.isValid == True`).

---

## 3. ROOT CAUSE: NEXT FRAME W MPV

### Diagnostyka zachowania libmpv + D3D11VA
- W trybie pauzy z akceleracją sprzętową D3D11VA komenda `self.mpv_player.command("frame-step")` nie wymuszała odświeżenia kolejki dekodera w osadzonym oknie libmpv na Windows. Pozycja `mpv.time_pos` pozostawała niezmienna (np. `9.999999999999993`).
- Z kolei `self.mpv_player.command("frame-back-step")` wykonywał wewnętrzny seek wstecz, co odświeżało dekoder (dlatego Previous Frame działał).
- Testy bezpośrednie na strumieniu wideo wykazały:
  - `mpv.command("frame-step")` -> `mpv.time_pos` bez zmian (brak przesunięcia klatki).
  - `mpv.seek(local_time, reference="absolute+exact")` -> natychmiastowe i precyzyjne przejście do klatki docelowej:
    - Klatka 300: `time_pos = 10.0100`
    - Klatka 301: `time_pos = 10.0434`
    - Klatka 302: `time_pos = 10.0767`
    - Klatka 303: `time_pos = 10.1101`

### Rozwiązanie: Deterministyczny Exact Seek w domenie Integer
- Przed wykonaniem kroku upewniono się, że odtwarzacz jest w stanie pauzy (`self.mpv_player.pause = True`).
- Zamiast polegać na asynchronicznym `frame-step`, zaimplementowano zunifikowaną ścieżkę dokładnego pozycjonowania `self.mpv_player.seek(local_time, reference="absolute+exact")`.
- Dodano śledzenie numeru bieżącej klatki w domenie liczb całkowitych (`self._playback_frame: int`), co zapobiega dryfowi zmiennoprzecinkowemu przy wielokrotnych kliknięciach (np. dla GoPro NTSC 29.97003 fps).
- Dodano szczegółowe logowanie diagnostyczne:
  ```text
  [FRAME STEP NEXT]
  paused=...
  mpv_time_before=...
  project_time_before=...
  current_frame=...
  target_frame=...
  same_clip=...
  clip_index=...
  local_target=...
  command=...
  mpv_time_after=...
  project_time_after=...
  actual_frame_after=...
  ```
  oraz kanoniczny log:
  ```text
  [FRAME STEP] before_frame=... target_frame=... after_frame=... project_time=... clip=... local_time=...
  ```

---

## 4. WYNIKI TESTÓW AUTOMATYCZNYCH

### A. Testy Fullscreen Lifecycle & Next Frame (`tests/test_gui_v4_fullscreen_and_next_frame.py`)
- `test_fullscreen_enter_does_not_destroy_normal_central`: **PASS** (`isValid(tabs) == True`)
- `test_fullscreen_exit_restores_same_qtabwidget`: **PASS** (`win.centralWidget() is original_tabs`, `isValid(preview) == True`)
- `test_fullscreen_twenty_toggle_cycles`: **PASS** (20 pełnych cykli enter/exit, 0 błędów RuntimeError, za każdym razem obiekty tabs i preview są w 100% sprawne)
- `test_fullscreen_esc_exit`: **PASS** (wyjście klawiszem ESC)
- `test_next_frame_advances_integer_domain`: **PASS** (krok N -> N+1 w całkowitych klatkach)
- `test_ten_times_next_and_ten_times_prev`: **PASS** (sekwencja: 10 kroków w przód z 300 do 310, a następnie 10 kroków wstecz powracająca dokładnie do 300 dla NTSC 29.97 fps)
- `test_multifile_boundary_next_and_prev`: **PASS** (płynne przekraczanie granicy klipów 014 -> 015 przy klatce 299 -> 300 i powrót 300 -> 299)

### B. Zestaw akceptacyjny GUI v3 (`tests/test_gui_v3_runtime_acceptance.py`)
- Wszystkie 6 testów: **PASS** (fonty, persystencja layoutu, eksport IN/OUT, fullscreen mode).

### C. Pełny pakiet regresyjny (fonty, wskaźniki, eksport, widgety)
- Wszystkie 44 testy: **PASS**.
- Łącznie: **57/57 PASSED (100% green)**.

---

## 5. GIT DIFF STAT
```text
 def_layout.json                       | 294 +++++++++++++------------
 src/gui/layout_manager.py             |   9 +-
 src/gui/qt/_mixins/indicator_mixin.py |   4 +
 src/gui/qt/_mixins/playback_mixin.py  | 119 +++++++++-
 src/gui/qt/_mixins/preset_mixin.py    |  82 ++++++-
 src/gui/qt/controller.py              |  16 ++
 src/gui/qt/main_window.py             | 117 ++++++++++
 src/gui/qt/models.py                  |  20 +-
 src/gui/qt/signals.py                 |  14 ++
 src/gui/qt/tabs/render_tab.py         | 129 ++++++++++-
 src/gui/qt/tabs/settings_tab.py       |  38 ++++
 src/gui/qt/widgets/data_stream_bar.py |   6 +
 src/gui/qt/widgets/property_editor.py | 124 ++++++++---
 src/gui/qt/widgets/video_preview.py   |  74 ++++++-
 src/indicators/compositor.py          |   8 +-
 src/indicators/gauge.py               | 114 +++++++---
 src/indicators/helpers.py             |   9 +-
 src/indicators/icons.py               | 403 ++++++++++++++++++++++++++++++----
 src/indicators/text.py                |  34 ++-
 src/indicators/time_display.py        |  10 +-
 tests/test_indicator_config_parity.py |   6 +
 tests/test_time_display_icon_size.py  |   6 +-
 22 files changed, 1349 insertions(+), 287 deletions(-)
```
*(Dla bieżącego etapu GUI v4 zmieniono wyłącznie `src/gui/qt/main_window.py` oraz `src/gui/qt/_mixins/playback_mixin.py`)*

---

## 6. FINAL VERDICT

| Funkcjonalność | Status | Uwagi |
| :--- | :---: | :--- |
| **FULLSCREEN ENTER** | **PASS** | Tabs bezpiecznie zachowane przez `takeCentralWidget()` |
| **FULLSCREEN ESC EXIT** | **PASS** | Wyjście klawiszem ESC przywraca ten sam obiekt `QTabWidget` |
| **FULLSCREEN REPEAT 20X** | **PASS** | 20 cykli wykonanych bez błędu; `shiboken6.isValid == True` |
| **TABS SURVIVE** | **PASS** | Obiekt C++ `tabs` nie jest niszczony przez Qt |
| **PREVIEW SURVIVES** | **PASS** | Obiekt C++ `preview` nie jest niszczony przez Qt |
| **NEXT FRAME** | **IMPLEMENTED — USER GUI ACCEPTANCE REQUIRED** | Dokładny `seek(reference="absolute+exact")` w domenie klatek całkowitych |
| **PREVIOUS FRAME** | **PASS** | Działa i zachowano dokładną pozycję |
| **NEXT/PREV AFTER FULLSCREEN**| **PASS** | Sterowanie klatkowe działa po wejściu i wyjściu z fullscreen |
| **MULTIFILE BOUNDARY** | **PASS** | Przejście 014 -> 015 i powrót 015 -> 014 zweryfikowane |

**STATUS OGÓLNY**: `IMPLEMENTED — USER GUI ACCEPTANCE REQUIRED`
*(Wszystkie testy automatyczne i symulacje headless są w 100% zielone; ostateczna wizualna ocena ruchu obrazu w oknie MPV wymaga sprawdzenia przez użytkownika w realnym GUI).*
