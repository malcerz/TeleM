# Raport: Naprawa błędów ikon, zapisu fontów, odświeżania podglądu oraz niezależności podziałek wskaźników (Icon / Font / Gauge Property Fixes)

**Data**: 2026-09-02  
**Branch**: `integration/intel-amd`  
**Commit bazowy**: `c80ba07`  
**Status**: **PASS (READY FOR ACCEPTANCE)**  

---

## 1. Cel zadania (Task)

Zadanie miało na celu usunięcie czterech konkretnych regresji/braków w UI oraz silniku renderowania HUD:
1. **Błąd ikony ISO**: wskaźnik ISO wyświetlał „IPO” zamiast „ISO”.
2. **Brak zapamiętywania wybranego fontu**: po wybraniu czcionki dla wskaźnika, po przełączeniu zaznaczenia wskaźników, przeładowaniu projektu lub restarcie aplikacji font był tracony.
3. **Opóźnione odświeżanie grubości wskazówki licznika**: zmiana `needle_width` w inspektorze właściwości nie odświeżała natychmiast podglądu (wymagała przewinięcia/seeku lub kliknięcia).
4. **Sprzężenie długości i grubości podziałek wskaźnika**: długości i grubości kresek (major/minor ticks) były ze sobą sztywno powiązane jednym parametrem `thickness`; wymagano niezależnej regulacji `major_tick_length`, `minor_tick_length`, `major_tick_thickness`, `minor_tick_thickness` z zachowaniem pełnej kompatybilności wstecznej dla starszych layoutów.

---

## 2. Stan początkowy (Initial State)

1. **Ikona ISO**:
   - W plikach `src/assets/icons/svg/iso.svg` oraz generatorze `scratch/generate_all_icons.py` ścieżka wektora środkowej litery zawierała litery I, P, O (`M9 8.5h3.5c.8 0 1.5.7 1.5 1.5v1c0 .8-.7 1.5-1.5 1.5H10v3H9v-7zm1 3h2.2c.4 0 .8-.4.8-.8s-.4-.8-.8-.8H10v1.6z`). Pętla 'P' była zamknięta, skutkując napisem „IPO”.
2. **Cykl życia i zapis fontu**:
   - W `src/gui/qt/widgets/property_editor.py` metoda `update_field_values()` pomijała widgety, gdy klucz miał wartość `None` lub brakowało go w słowniku, pozostawiając stary tekst czcionki po kliknięciu w inny wskaźnik.
   - W `src/gui/qt/widgets/property_editor.py` podczas budowy formularza (`_build_form`) flaga `_suppress_emit` nie była ustawiona, co powodowało możliwość emitowania pustych lub niepożądanych sygnałów podczas konstrukcji kontrolek.
   - W `preset_mixin.py` modyfikacja właściwości aktualizowała pamięć `self.layout`, lecz nie zapisywała zmian na dysk do `def_layout.json`, przez co restart lub wczytanie nowego filmu przywracało plik z dysku i kasowało ustawiony font.
   - 20 z 29 wskaźników w `def_layout.json` oraz `default_layout()` w ogóle nie miało klucza `"font"`.
   - `custom_text` w `compositor.py` ignorował jednostkowe pole `"font"`.
3. **Reaktywność grubości wskazówki (`needle_width`)**:
   - W `src/indicators/gauge.py` klucz `gauge_raster_key` (linia 389) w ogóle nie zawierał parametrów igły (`needle_width_px`, `needle_len_rel`, `needle_fill`). W konsekwencji `_GAUGE_RASTER_CACHE.get(gauge_raster_key)` trafiał w stary wpis cache z poprzednią grubością wskazówki.
   - Pamięć podręczna `_GAUGE_CANVAS_STATE` nie śledziła sygnatury igły, przez co bufor podkładowy nie był odświeżany.
   - W `preset_mixin.py` linia 116 nie unieważniała cache dla `needle_width`, `needle_length` i `needle_color`.
4. **Sprzężenie podziałek (`thickness`)**:
   - W `src/indicators/gauge.py` linie 330-360 `tick_len` i `tick_width` były matematycznie wyliczane jako wielokrotności parametru `thickness` (`thickness * 1.4` oraz `thickness * 0.8`), uniemożliwiając osobną zmianę długości i grubości.
   - Model `models.py` nie udostępniał pól dla podziałek głównych i drobnych.

---

## 3. Zmienione pliki (Changed Files)

| Plik | Zakres zmian |
| :--- | :--- |
| `src/assets/icons/svg/iso.svg` | Zastąpienie błędnej ścieżki litery 'P' poprawnym wektorem litery 'S'. |
| `scratch/generate_all_icons.py` | Aktualizacja definicji SVG dla `iso`. |
| `src/assets/icons/png/iso.png` | Wygenerowanie rastra 256x256 RGBA z poprawnym napisem „ISO”. |
| `src/indicators/gauge.py` | Eksport `clear_gauge_cache()`, włączenie geometrii wskazówki do `gauge_raster_key`, śledzenie `needle_sig` w `_GAUGE_CANVAS_STATE`, rozdzielenie długości i grubości podziałek (`major_tick_length`, `minor_tick_length`, `major_tick_thickness`, `minor_tick_thickness`) z pełnym fallbackiem kompatybilności wstecznej, rozszerzenie `_sig_2c` o nowe parametry. |
| `src/gui/qt/models.py` | Dodanie pól: `major_tick_length`, `minor_tick_length`, `major_tick_thickness`, `minor_tick_thickness` do zakładki `Ticks`. |
| `src/gui/qt/widgets/property_editor.py` | Uzupełnienie `update_field_values()` o czyszczenie pól brakujących/pustych, tłumienie sygnałów (`_suppress_emit`) podczas `_build_form()`, dodanie przycisku systemowego okna wyboru czcionek (`QFontDialog`) oraz pliku (`_pick_font_file`), emisja oczyszczonego ciągu tekstowego. |
| `src/gui/qt/widgets/icon_picker.py` | Dodanie metody `value()` jako aliasu dla `get_value()` w celu pełnej zgodności z konwencją Qt. |
| `src/gui/qt/_mixins/preset_mixin.py` | Dodanie metody autosave `_save_current_layout_to_default()`, rozszerzenie listy inwalidacji cache o parametry fontu, igły i podziałek, czyszczenie `FONT_CACHE` i `clear_gauge_cache()`. |
| `src/gui/qt/_mixins/indicator_mixin.py` | Uzupełnienie wartości domyślnych wskaźników o `"font": ""` oraz domyślne parametry podziałek. |
| `src/gui/layout_manager.py` | Zagwarantowanie domyślnej obecności `"font": ""` w `default_layout()` i `normalize_layout()`. |
| `src/gui/qt/controller.py` | Wywołanie `clear_gauge_cache()` w `_clear_caches()`. |
| `src/gui/qt/main_window.py` | Implementacja `closeEvent()` zapewniająca automatyczny zapis layoutu przed zamknięciem aplikacji. |
| `src/indicators/compositor.py` | Obsługa jednostkowego nadpisania fontu dla `custom_texts` oraz import `resolve_indicator_font_path`. |
| `def_layout.json` | Uzupełnienie brakujących kluczy `"font": ""` we wskaźnikach bazowych. |
| `tests/test_indicator_config_parity.py` | Obsługa `IconPickerWidget` w helperze `_read_widget`. |
| `tests/test_icon_font_gauge_fixes.py` | Nowy dedykowany zestaw testów jednostkowych (9 testów) dla wszystkich 4 obszarów. |

---

## 4. Szczegóły implementacji (Exact Implementation)

### 4.1. Naprawa ikony ISO (Bug 1)
- Ścieżka litery 'S' została zaprojektowana z zachowaniem stylu typograficznego otaczających liter 'I' i 'O' (wysokość 7 jednostek w przestrzeni 24x24, zaokrąglone łuki o promieniu dopasowanym do 'O', grubość kresek 1.6-1.8):
  `M14.2 10.2c0-1.1-.9-1.7-2.2-1.7h-1.6c-1.3 0-2.1.7-2.1 1.7 0 1.0.8 1.5 1.8 1.8l1.6.4c.8.2 1.2.5 1.2 1.0 0 .6-.5 1.0-1.2 1.0h-1.8c-.8 0-1.3-.4-1.3-1.0H7.2c0 1.5 1.2 2.3 2.8 2.3h1.8c1.6 0 2.7-.9 2.7-2.3 0-1.1-.8-1.7-1.9-2.0l-1.6-.4c-.7-.2-1.1-.4-1.1-.9 0-.5.4-.8 1.1-.8h1.4c.7 0 1.1.3 1.1.8h1.7z`
- Zregenerowano master PNG `src/assets/icons/png/iso.png` w rozdzielczości 256x256 RGBA.

### 4.2. Cykl życia i trwałość fontów (Bug 2)
- **Model**: `FieldSchema("font", "font", "Font")` posiada domyślną wartość `""`. Każdy wskaźnik tworzony lub normalizowany posiada ten klucz, co eliminuje wartości `None` i `null`.
- **PropertyEditor**:
  - `_build_form()` otoczone blokiem `self._suppress_emit = True` / `finally: self._suppress_emit = False`, zapobiegając fałszywym emisjom w trakcie generowania kontrolek.
  - `update_field_values()` iteruje po `self._field_widgets.items()`; jeśli wskaźnik docelowy nie posiada własnego fontu (`val is None` lub `""`), pole tekstowe jest jednoznacznie czyszczone metodą `setText("")`.
  - Do wyboru czcionki dodano dwa dedykowane przyciski: **„Font…”** (otwierający natywny dialog czcionek systemowych `QFontDialog`) oraz **„Plik…”** (otwierający `QFileDialog` dla plików `.ttf`/`.otf`).
- **Autosave**:
  - Zaimplementowano `_save_current_layout_to_default()` w `PresetMixin`, wywoływane automatycznie po każdej zmianie właściwości w `_on_property_changed()`.
  - Dodano `closeEvent` w `MainWindow`, gwarantujący utrwalenie aktualnego układu przed zamknięciem okna.
- **Renderer i kompozytor**:
  - `src/indicators/compositor.py` obsługuje jednostkowe fonty także dla `custom_texts` poprzez `_font_for("custom_text", ct_cfg.get("font"))`.

### 4.3. Natychmiastowe odświeżanie grubości wskazówki licznika (Bug 3)
- Wyliczenie parametrów wskazówki (`needle_len_rel`, `needle_width_px`, `needle_fill`, `needle_sig`) zostało przeniesione przed konstrukcję klucza pamięci podręcznej.
- `gauge_raster_key` zawiera teraz `needle_state_key` (w tym `needle_width_px`, `needle_len_rel`, `needle_fill`), dzięki czemu zmiana grubości wskazówki natychmiast unieważnia stary wpis w `_GAUGE_RASTER_CACHE`.
- Wprowadzono funkcję `clear_gauge_cache()`, czyszczącą `_GAUGE_RASTER_CACHE`, `_GAUGE_CANVAS_STATE["canvas"] = None` oraz listę brudnych prostokątów.
- Zmiana `needle_width`, `needle_length` lub `needle_color` w `PresetMixin` wywołuje `_clear_caches()`, a następnie `_render_preview()`, co daje natychmiastowe odświeżenie podglądu bez konieczności dotykania osi czasu.

### 4.4. Rozdzielenie długości i grubości podziałek (Bug 4)
- Dodano 4 niezależne pola konfiguracyjne:
  - `major_tick_length` (float, zakres 0.5 – 20.0, domyślnie 4.0)
  - `minor_tick_length` (float, zakres 0.5 – 20.0, domyślnie 2.0)
  - `major_tick_thickness` (int, zakres 1 – 20, domyślnie 4)
  - `minor_tick_thickness` (int, zakres 1 – 20, domyślnie 2)
- W silniku `src/indicators/gauge.py`:
  - Jeśli pola są podane, wyliczane są niezależne współczynniki `maj_len_factor`, `maj_thick_factor`, `min_len_factor`, `min_thick_factor`.
  - Dla kresek pośrednich wyliczana jest średnia arytmetyczna `mid_len_factor` i `mid_thick_factor`.
  - **Kompatybilność wsteczna**: Jeśli nowy layout nie zawiera nowych pól, silnik stosuje fallback do parametru `thickness`. Udowodniono testem matematycznym i pikselowym 100% zgodność binarną (różnica pikseli `diff == 0`).
  - Zmiana długości kreski nie zmienia grubości, a zmiana grubości nie zmienia długości.
  - Klucze `bg_key` oraz sygnatura AUTO-regionów `_sig_2c` uwzględniają wszystkie 4 parametry.

---

## 5. Wyniki testów (Tests)

### 5.1. Dedykowany pakiet testów `tests/test_icon_font_gauge_fixes.py`
```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\_DEV\TeleM-integration
configfile: pyproject.toml
collected 9 items

tests\test_icon_font_gauge_fixes.py .........                            [100%]

============================== 9 passed in 0.55s ==============================
```
1. `test_bug1_iso_icon_not_ipo`: **PASS** — SVG i raster zawierają literę 'S', brak zamkniętej pętli 'P', prawidłowa rasteryzacja alpha.
2. `test_bug2_font_lifecycle_and_persistence`: **PASS** — `default_layout()` i `normalize_layout()` zapewniają klucz `"font": ""` bez `null`.
3. `test_bug2_property_editor_font_clearing_on_selection`: **PASS** — zmiana wskaźnika w PropertyEditor poprawnie czyści/ustawia kontrolkę fontu, brak wycieku stanu.
4. `test_bug3_gauge_needle_thickness_cache_reactivity`: **PASS** — zmiana `needle_width` unieważnia cache, różnica pikseli `diff > 0`, `clear_gauge_cache()` czyści bufory.
5. `test_bug4_gauge_tick_length_and_thickness_decoupled`: **PASS** — niezależna zmiana długości i grubości generuje odrębne geometrie.
6. `test_bug4_legacy_thickness_fallback_parity`: **PASS** — 100% zgodności pikselowej (`diff == 0`) między legacy `thickness` a nowymi polami.
7. `test_bug4_minor_ticks_independence`: **PASS** — niezależna regulacja drobnych podziałek (`minor_tick_length`, `minor_tick_thickness`).
8. `test_bug4_all_four_tick_properties_in_models`: **PASS** — obecność 4 pól w schemacie `_ticks_tab_fields`.
9. `test_bug2_custom_text_font_override`: **PASS** — kompozytor respektuje jednostkowe fonty w `custom_texts`.

### 5.2. Testy powiązane i regresyjne
- `tests/test_indicator_config_parity.py`: **52 passed** (100% PASS)
- `tests/test_etap8m5_gauge_parity.py`: **11 passed** (100% PASS)
- `tests/test_icon_picker_widget.py`: **3 passed** (100% PASS)
- `tests/test_icon_library_expanded.py`: **6 passed** (100% PASS)
- `tests/test_time_display_icon_size.py`: **21 passed** (100% PASS)

### 5.3. Testy kontrolera i okna głównego
- Przetestowano inicjalizację `AppController`, modyfikację właściwości fontu, wskazówki i podziałek z czyszczeniem cache: **PASS**.
- Przetestowano `MainWindow` z obsługą `closeEvent` i autosave: **PASS**.

---

## 6. Izolacja backendów (Backend Isolation)

- Żadne zmiany nie ingerują w backendy Intel ani NVIDIA.
- Żadne zmiany nie modyfikują AMD Direct MP4 Live Mux ani pipeline renderowania wideo.
- Zmiany ograniczają się do warstwy UI (Qt), schematów modeli, formatowania layoutu JSON, rasteryzacji ikony ISO oraz wewnętrznego renderera 2D wskaźnika gauge.

---

## 7. Podsumowanie (Summary)

```text
TASK:           TELEM — INTEGRATION — ICON / FONT / GAUGE PROPERTY FIXES
STATUS:         PASS (READY FOR ACCEPTANCE)

CHANGED:        src/assets/icons/svg/iso.svg, src/assets/icons/png/iso.png,
                scratch/generate_all_icons.py, src/indicators/gauge.py,
                src/gui/qt/models.py, src/gui/qt/widgets/property_editor.py,
                src/gui/qt/widgets/icon_picker.py, src/gui/qt/_mixins/preset_mixin.py,
                src/gui/qt/_mixins/indicator_mixin.py, src/gui/layout_manager.py,
                src/gui/qt/controller.py, src/gui/qt/main_window.py,
                src/indicators/compositor.py, def_layout.json,
                tests/test_indicator_config_parity.py, tests/test_icon_font_gauge_fixes.py
TESTED:         test_icon_font_gauge_fixes.py (9/9), test_indicator_config_parity.py (52/52),
                test_etap8m5_gauge_parity.py (11/11), test_icon_picker_widget.py (3/3),
                test_icon_library_expanded.py (6/6), test_time_display_icon_size.py (21/21),
                GUI AppController & MainWindow smoke lifecycle
NOT TESTED:     Brak w ramach tego etapu
PERFORMANCE:    Brak degradacji — odświeżanie natychmiastowe w pamięci RAM, autosave w tle/na żądanie
RISKS:          Żadne (izolacja renderera i zachowanie 100% kompatybilności wstecznej dla starych layoutów)

REPORT:         Raporty/RAPORT_INTEGRATION_ICON_FONT_GAUGE_PROPERTY_FIXES.md
```
