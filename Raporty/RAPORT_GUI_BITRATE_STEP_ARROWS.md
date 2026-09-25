# RAPORT: GUI BITRATE STEP ARROWS & SEMANTICS

## 1. Cel zadania
Poprawić kontrolkę bitrate w zakładce `Rendering`:
1. **Semantyka przycisków:**
   - Lewy przycisk: zmiana wartości o `-1 Mb/s` (`current_bitrate - 1`).
   - Prawy przycisk: zmiana wartości o `+1 Mb/s` (`current_bitrate + 1`).
   - Zachowanie ograniczeń (clamping): minimalna wartość `5 Mb/s`, maksymalna `120 Mb/s`.
2. **Natywne ikony i styl Qt:**
   - Zastąpienie starych oznaczeń tekstowych `|<` i `>|` komponentami `QToolButton` z natywnymi ikonami standardowymi Qt: `QStyle.SP_ArrowLeft` oraz `QStyle.SP_ArrowRight`.
   - Przyciski małe, kwadratowe (`24x24 px`), bez tekstu, spójne wizualnie z motywem interfejsu.
3. **Synchronizacja:**
   - Natychmiastowa, dwukierunkowa synchronizacja pomiędzy przyciskami, suwakiem `QSlider`, polem tekstowym `QLineEdit` (`40 Mb/s`) oraz metodą `BitrateControl.text()` (`40M`).
4. **Izolacja backendu:**
   - Brak modyfikacji backendu, enkoderów AMD/Intel/NVIDIA ani innych elementów GUI.

---

## 2. Podsumowanie Weryfikacji

```text
LEFT_BUTTON_STEP=-1
RIGHT_BUTTON_STEP=+1
MIN_CLAMP=5
MAX_CLAMP=120
NATIVE_QT_ARROWS=True
BITRATE_SYNC=PASS
BACKEND_MODIFIED=False
CASE=CASE A — BITRATE STEP ARROWS FULL PASS
```

---

## 3. Szczegóły Implementacji

### 3.1. Zmiany w `src/gui/qt/widgets/discrete_slider.py`
- Klasa `BitrateControl`:
  - `self.btn_left = QToolButton()` ze standardową ikoną `QStyle.SP_ArrowLeft`, podłączony do slotu `_on_dec_clicked` (`self.setValue(self.value() - 1)`).
  - `self.btn_right = QToolButton()` ze standardową ikoną `QStyle.SP_ArrowRight`, podłączony do slotu `_on_inc_clicked` (`self.setValue(self.value() + 1)`).
  - Przyciski mają ustalony stały rozmiar `24x24 px` oraz minimalistyczny styl bez zbędnych obramowań.
  - Metoda `setValue(val)` zapewnia automatyczne przycinanie w przedziale `[5, 120]`, ustawienie suwaka, aktualizację tekstu (`{val} Mb/s`) oraz emisję sygnałów `valueChanged` i `textChanged`.

### 3.2. Testy jednostkowe w `tests/test_render_tab_controls_cleanup.py`
- Zaktualizowano test `test_bitrate_control_sync_and_buttons`:
  - Krok `-1` (np. start 10 -> 9 Mb/s, suwak=9, text()='9M').
  - Krok `+1` (np. 9 -> 10 -> 11 Mb/s, suwak=11, text()='11M').
  - Granice: `5 + left = 5` oraz `120 + right = 120`.
  - Płynny ruch suwakiem i manualny wpis z poprawnym parsowaniem i clampem.

---

## 4. Wyniki Testów

### 4.1. Wynik Pytest (`scratch/gui_bitrate_step_arrows/tests.txt`)
```text
tests/test_render_tab_controls_cleanup.py::test_quality_preset_slider PASSED [ 12%]
tests/test_render_tab_controls_cleanup.py::test_resolution_slider PASSED [ 25%]
tests/test_render_tab_controls_cleanup.py::test_update_rate_slider PASSED [ 37%]
tests/test_render_tab_controls_cleanup.py::test_hud_resolution_slider PASSED [ 50%]
tests/test_render_tab_controls_cleanup.py::test_bitrate_control_sync_and_buttons PASSED [ 62%]
tests/test_render_tab_controls_cleanup.py::test_render_tab_controls_integration PASSED [ 75%]
tests/test_render_tab_controls_cleanup.py::test_preview_alignment_project_vs_render PASSED [ 87%]
tests/test_render_tab_controls_cleanup.py::test_output_dialog_prefill_logic PASSED [100%]
============================== 8 passed in 1.61s ==============================
```

### 4.2. Weryfikacja Real GUI
- Skrypt `scratch/gui_bitrate_step_arrows/capture_bitrate_control.py` uruchomił pełne GUI `BikeRideHUD.py` i zapisał zrzuty:
  - `scratch/gui_bitrate_step_arrows/bitrate_control.png`: Wygląd kontrolki z wektorowymi strzałkami lewo/prawo, suwakiem i polem wartości.
  - `scratch/gui_bitrate_step_arrows/rendering_controls_updated.png`: Całościowy zrzut panelu ustawień renderowania.
