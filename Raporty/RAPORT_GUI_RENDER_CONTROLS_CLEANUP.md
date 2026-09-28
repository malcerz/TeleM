# RAPORT: GUI RENDER CONTROLS CLEANUP & PREVIEW ALIGNMENT

## 1. Cel zadania
Wykonać korekty interfejsu użytkownika w zakładkach `Projekt` i `Rendering`:
1. **Wyrównanie okna podglądu (Projekt vs Rendering):** Usunięcie niepotrzebnego przesunięcia w lewo w zakładce Rendering; identyczne marginesy, spacing i rozmiar 16:9 podglądu w obu zakładkach.
2. **Preset jakości AMD jako suwak dyskretny:** Zamiana listy wyboru na `DiscreteSlider` z 3 pozycjami (`Fast` | `Balanced` | `Quality`), etykietami tekstowymi, bez stanów pośrednich, z zachowaniem mapowania `FAST`, `BALANCED`, `QUALITY`.
3. **Rozdzielczość jako suwak dyskretny:** Zamiana listy na `DiscreteSlider` ze wszystkimi wspieranymi wartościami (`480p`, `720p`, `1080p`, `4k`, `5.3k`, `8k`, `source`).
4. **Częstotliwość HUD jako suwak dyskretny:** Zamiana listy na `DiscreteSlider` (`Quarter`, `Half`, `Full`).
5. **Rozdzielczość HUD jako suwak dyskretny:** Zamiana listy na `DiscreteSlider` (`50%`, `75%`, `100%`, `Auto`).
6. **Bitrate jako spójny zestaw kontrolek:** Zintegrowany widget `BitrateControl`: `[|<]` (MIN: 5 Mb/s), płynny suwak `QSlider` (5..120 Mb/s), `[>|]` (MAX: 120 Mb/s) oraz pole ręcznego wpisu `QLineEdit` z dwukierunkową synchronizacją i formatem `40 Mb/s`.
7. **Naprawa dialogu pliku wyjściowego:** Przekazywanie bieżącego folderu i proponowanej nazwy pliku z pola `edit_output` do dialogu `QFileDialog.getSaveFileName` oraz zapamiętywanie ostatnio wybranego folderu przy ponownym otwarciu.

---

## 2. Podsumowanie Weryfikacji

```text
PROJECT_PREVIEW_LEFT_X=2
RENDERING_PREVIEW_LEFT_X=2
PREVIEW_ALIGNMENT=PASS

AMD_PRESET_SLIDER=PASS
RESOLUTION_SLIDER=PASS
FPS_SLIDER=PASS
HUD_RESOLUTION_SLIDER=PASS

BITRATE_SLIDER=PASS
BITRATE_MIN_BUTTON=PASS
BITRATE_MAX_BUTTON=PASS
BITRATE_MANUAL_INPUT=PASS
BITRATE_SYNC=PASS

OUTPUT_DIALOG_PREFILL=PASS
OUTPUT_DIALOG_REOPEN=PASS

BACKEND_AMD_MODIFIED=False
USER_VISUAL_ACCEPTANCE=PENDING

MODIFIED_FILES=src/gui/qt/tabs/render_tab.py, src/gui/qt/widgets/__init__.py
CREATED_FILES=src/gui/qt/widgets/discrete_slider.py, tests/test_render_tab_controls_cleanup.py, scratch/gui_render_controls_cleanup/run_gui_validation.py
DEFERRED_FINDINGS=none
CASE=CASE A — GUI CLEANUP FULL PASS
```

---

## 3. Szczegóły Implementacji

### 3.1. Usunięcie różnic layoutu podglądu
- W `RenderTab._build_ui()`:
  - Usunięto margines zewnętrzny `vbox.setContentsMargins(0, 0, 0, 0)` (zgodnie z `ProjectTab`).
  - Ustawiono `self.left_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)` oraz `left_layout.setContentsMargins(0, 4, 4, 4)`.
  - Usunięto flagę `Qt.AlignHCenter` z `self.preview_slot`, dzięki czemu podgląd przylega dokładnie do tej samej pozycji co w zakładce `Projekt`.
  - Dodano metody `showEvent`, `resizeEvent` oraz `_update_preview_width()` wyliczające wymiary 16:9 (`preview_aspect_size(total_h, total_w)`) identycznie jak w `ProjectTab`.

### 3.2. Widget `DiscreteSlider`
- Implementacja w `src/gui/qt/widgets/discrete_slider.py`.
- Dyskretny `QSlider` z krokami całkowitymi, pozycjami ticków pod suwakiem oraz klikalnymi etykietami `ClickableLabel`.
- Kliknięcie etykiety natychmiast przestawia suwak na dany indeks.
- Aktywna pozycja jest wyróżniona pogrubionym kolorem akcentu `#d44000`.
- Pełna kompatybilność z kontraktem `QComboBox`:
  - `currentText()`, `currentData()`, `setCurrentText()`, `setCurrentIndex()`, `currentIndex()`, `count()`, `findText()`, `findData()`, sygnały `currentIndexChanged`, `currentTextChanged`.

### 3.3. Widget `BitrateControl`
- Zintegrowany widget `BitrateControl`:
  - Przycisk `|<` ustawia minimalny dozwolony bitrate (`5 Mb/s`).
  - Suwak `QSlider` (5..120 Mb/s) z natychmiastową aktualizacją pola tekstowego.
  - Przycisk `>|` ustawia maksymalny dozwolony bitrate (`120 Mb/s`).
  - Pole `QLineEdit` wyświetlające `40 Mb/s` z obsługą ręcznego wpisywania wartości numerycznych i automatycznym ograniczaniem (clamping 5..120).
  - Metoda `text()` zwraca czysty format kontraktowy (np. `40M`), w pełni zgodny z parserami `amd_config.py`, `nvidia_native_exporter.py` i `command_builder.py`.

### 3.4. Naprawa dialogu pliku wyjściowego
- W `RenderTab._select_output()`:
  - Odczyt bieżącego tekstu z `self.edit_output`.
  - Jeżeli ścieżka jest bezwzględna (`C:\Videos\MojaJazda.mp4`), dialog otwiera katalog `C:\Videos` z nazwą `MojaJazda.mp4`.
  - Jeżeli podano samą nazwę pliku, dialog łączy ją z `self._last_output_dir` (lub bieżącym katalogiem roboczym).
  - Po zatwierdzeniu pliku, katalog zostaje zapamiętany w `self._last_output_dir` na potrzeby kolejnych wywołań dialogu.

---

## 4. Wyniki Testów

### 4.1. Testy Jednostkowe i Integracyjne (`tests/test_render_tab_controls_cleanup.py`)
```text
tests/test_render_tab_controls_cleanup.py::test_quality_preset_slider PASSED [ 12%]
tests/test_render_tab_controls_cleanup.py::test_resolution_slider PASSED [ 25%]
tests/test_render_tab_controls_cleanup.py::test_update_rate_slider PASSED [ 37%]
tests/test_render_tab_controls_cleanup.py::test_hud_resolution_slider PASSED [ 50%]
tests/test_render_tab_controls_cleanup.py::test_bitrate_control_sync_and_buttons PASSED [ 62%]
tests/test_render_tab_controls_cleanup.py::test_render_tab_controls_integration PASSED [ 75%]
tests/test_render_tab_controls_cleanup.py::test_preview_alignment_project_vs_render PASSED [ 87%]
tests/test_render_tab_controls_cleanup.py::test_output_dialog_prefill_logic PASSED [100%]
============================== 8 passed in 1.67s ==============================
```

### 4.2. Pomiary Real GUI (`scratch/gui_render_controls_cleanup/gui_test.txt`)
- `PROJECT TAB preview_slot local_x=0, global_x=2, size=(951, 534)`
- `RENDERING TAB preview_slot local_x=0, global_x=2, size=(951, 534)`
- `PREVIEW_ALIGNMENT: PASS`
- `BITRATE MIN`: 5 Mb/s (`5M`)
- `BITRATE MID`: 40 Mb/s (`40M`)
- `BITRATE MAX`: 120 Mb/s (`120M`)
- `OUTPUT_DIALOG`: folder=`C:\Videos`, file=`MojaJazda.mp4`

---

## 5. Artefakty Wizualne
Wszystkie artefakty zapisano w katalogu `scratch/gui_render_controls_cleanup/`:
- `project_preview.png`: Pełny zrzut zakładki Projekt z podglądem wideo.
- `rendering_preview.png`: Pełny zrzut zakładki Rendering z identycznym położeniem podglądu.
- `rendering_controls.png`: Zrzut panelu ustawień eksportu z nowymi dyskretnymi suwakami i kontrolką bitrate.
- `bitrate_min.png`: Stan kontrolki bitrate po kliknięciu `|<` (5 Mb/s).
- `bitrate_mid.png`: Stan kontrolki bitrate przy wartości 40 Mb/s.
- `bitrate_max.png`: Stan kontrolki bitrate po kliknięciu `>|` (120 Mb/s).
- `output_dialog_prefilled.png`: Zrzut dialogu zapisu z poprawnie wstępnie wypełnionym katalogiem i nazwą pliku.
