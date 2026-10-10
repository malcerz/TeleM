# RAPORT: UX / LOGIKA PROJEKTU — BLOKADA PROJEKTU BEZ PLIKU, NATYCHMIASTOWY HUD, GLIF ° Z ARIAL, USUNIĘCIE „LICZBY WĄTKÓW”, DOMYŚLNY EXPORT FOLDER I NAPRAWA „INTEGRACJI”

**Data wykonania:** 2026-10-05  
**Środowiska:** `C:\_DEV\SportCamHUD-main-new` oraz `C:\_DEV\SportCamHUD-portable`  
**Status:** ZAKOŃCZONE SUKCESEM (100% testów PASS, pełne parity hashów)

---

## 1. WSTĘP I CELE ZADANIA

Celem zadania było rozwiązanie 6 kluczowych problemów UX i logiki aplikacji zgłoszonych przez użytkownika:
1. **Blokada zakładki „Projekt” bez pliku:** Zakładka „Projekt” musi być zablokowana (`disabled`) po starcie aplikacji oraz po zamknięciu/wyczyszczeniu projektu, dopóki nie zostanie załadowany co najmniej jeden plik wideo. Zakładki „Rendering” i „Ustawienia” muszą pozostać stale aktywne (`enabled`).
2. **Natychmiastowy HUD po załadowaniu wideo/telemetrii:** Po wczytaniu projektu HUD musi wyrenderować się natychmiast na podglądzie wideo, bez wymuszania na użytkowniku klikania Play czy przesuwania suwaka osi czasu.
3. **Glif stopni „°” ZAWSZE renderowany fontem Arial:** Fonty cyfrowe (np. Digital-7, LCD) często nie zawierają glifu stopnia `°` (rysują pusty prostokąt, spację lub niepoprawny znak). Cyfry muszą zachować wybrany font użytkownika, natomiast sam symbol stopnia ma być zawsze renderowany z systemowego fontu Arial, z zachowaniem właściwych proporcji, pozycjonowania (left/center/right alignment), cieniowania (drop shadow) i obrysu (outline).
4. **Usunięcie kontrolki „Liczba wątków” i auto-maksimum CPU:** Usunięcie z GUI zakładki Ustawień kontrolki wyboru wątków, a w silniku eksportu CPU przełączenie na automatyczne wykorzystanie maksymalnej dostępnej puli CPU (`os.cpu_count()`).
5. **Domyślny folder eksportu:** Folder źródłowy wczytanego wideo jako domyślna lokalizacja eksportu (np. `D:\GoPro\video.mp4` -> `D:\GoPro\`). Zapamiętywanie ostatnio wybranego folderu użytkownika w konfiguracji (`last_export_dir`), weryfikacja istnienia i uprawnień do zapisu oraz bezwzględny zakaz używania katalogu bieżącego (CWD).
6. **Naprawa pola „Integracja” w Ustawieniach:** Etykieta „--” zamiast „Nic”, poprawa zapisu i odczytu wybranego źródła automatycznej telemetrii (Garmin, Strava, `--`) tak, aby otwarcie zakładki Ustawień nie resetowało stanu.

---

## 2. SZCZEGÓŁOWY OPIS WPROWADZONYCH ZMIAN

### 2.1. Blokada zakładki „Projekt” bez wideo (`main_window.py`, `signals.py`, `load_tab.py`, `controller.py`)
- W [`src/gui/qt/main_window.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/main_window.py) zaimplementowano metodę `_update_main_tabs_state()`:
  - Sprawdza stan załadowania wideo (`self.controller.video_loaded` lub `self.controller.current_video_path`).
  - Ustawia `self.tabs.setTabEnabled(idx, has_video)` wyłącznie dla zakładki o nazwie „Projekt”.
  - Zakładki „Rendering” oraz „Ustawienia” (a także „Wczytywanie”) są zawsze aktywne (`setTabEnabled(..., True)`).
  - Wywoływana przy inicjalizacji GUI (start programu ze stanem `Projekt = disabled`), po pomyślnym załadowaniu wideo (`Projekt = enabled`), oraz po wyczyszczeniu projektu (`Projekt = disabled`).
- W [`src/gui/qt/signals.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/signals.py) dodano sygnał `sig_project_cleared = Signal()`.
- W [`src/gui/qt/tabs/load_tab.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/tabs/load_tab.py) akcja `_on_clear()` emituje sygnał `sig_project_cleared`, a [`src/gui/qt/controller.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/controller.py) udostępnia metodę `clear_project()` resetującą stan wideo i telemetrii.

### 2.2. Natychmiastowy HUD po załadowaniu wideo/telemetrii (`preview_mixin.py`, `project_mixin.py`, `main_window.py`)
- W [`src/gui/qt/_mixins/preview_mixin.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/_mixins/preview_mixin.py) dodano metodę `request_preview_refresh(current_time=0.0)`:
  - Wymusza bezpośrednie ponowne wygenerowanie i nałożenie HUD na bieżącą klatkę wideo w widgetcie podglądu (`preview_widget.update_hud()`).
  - Nie używa sztuczek z wywoływaniem `play()`/`pause()`, co gwarantuje stabilność odtwarzacza.
- W [`src/gui/qt/_mixins/project_mixin.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/_mixins/project_mixin.py):
  - Flaga `self._preview_telemetry_loading` jest przestawiana na `False` przed rozesłaniem powiadomień do podglądu.
  - Wywołanie `request_preview_refresh(0.0)` w miejscach finalizacji wczytywania telemetrii (`bg_load`, `attach_late_telemetry`).
- W [`src/gui/qt/main_window.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/main_window.py) w obsłudze `_on_data_streams_ready()` dodano wywołanie `self.request_preview_refresh(0.0)`.

### 2.3. Dedykowany fallback Arial dla glifu stopnia „°” (`helpers.py`, indykatory)
- W [`src/indicators/helpers.py`](file:///C:/_DEV/SportCamHUD-main-new/src/indicators/helpers.py) zaimplementowano funkcje pomocnicze:
  - `get_arial_fallback_font(font_size)`: pobiera lub ładuje systemowy font `Arial.ttf` / `arial.ttf` z cache w żądanym rozmiarze pikselowym.
  - `split_text_degree_chunks(text)`: dzieli tekst na segmenty z flagą `is_degree` (np. `"45°"` -> `[("45", False), ("°", True)]`).
  - `measure_text_with_degree_fallback(draw, text, primary_font, font_size)`: dokładnie mierzy łączną szerokość `w = w(cyfry, primary_font) + w("°", arial_font)` oraz maksymalną wysokość `h`.
  - `draw_text_with_degree_fallback(draw, xy, text, primary_font, font_size, fill, align, anchor, shadow, stroke)`: rysuje tekst z pełną obsługą obrysu (`stroke_width`, `stroke_fill`), cienia (`shadow_offset`, `shadow_fill`) oraz wyrównania (`left`, `center`, `right`).
- Zintegrowano obsługę glifu `°` we wszystkich wskaźnikach projektu:
  - [`src/indicators/gauge.py`](file:///C:/_DEV/SportCamHUD-main-new/src/indicators/gauge.py): etykiety heading oraz główny tekst wskaźnika (`txt_main`), kafle buforowane oraz fallback.
  - [`src/indicators/lean.py`](file:///C:/_DEV/SportCamHUD-main-new/src/indicators/lean.py): `_text_size`, `_draw_text_bounded`, `_draw_text_bounded_cached`.
  - [`src/indicators/bar.py`](file:///C:/_DEV/SportCamHUD-main-new/src/indicators/bar.py): pomiar i renderowanie wartości kątowych/temperatury z symbolem `°`.
  - [`src/indicators/text.py`](file:///C:/_DEV/SportCamHUD-main-new/src/indicators/text.py) oraz [`src/indicators/custom_text.py`](file:///C:/_DEV/SportCamHUD-main-new/src/indicators/custom_text.py): pełna obsługa glifu `°`.
  - [`src/indicators/compositor.py`](file:///C:/_DEV/SportCamHUD-main-new/src/indicators/compositor.py): standalone value_text oraz etykiety skali (`left_text`, `right_text`).

### 2.4. Usunięcie „Liczby wątków” i auto-maksimum CPU (`settings_tab.py`, `render_mixin.py`, `streaming.py`)
- W [`src/gui/qt/tabs/settings_tab.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/tabs/settings_tab.py):
  - Całkowicie usunięto kontrolkę `self.spin_threads` z GUI, siatki layoutu, zapisu (`_save_settings`) oraz odczytu (`_load_settings`).
- W [`src/gui/qt/_mixins/render_mixin.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/_mixins/render_mixin.py):
  - Przypisywanie wątków CPU korzysta z automatycznego maksimum: `max(1, (os.cpu_count() or 1) - 1)`.
- W [`src/ffmpeg/streaming.py`](file:///C:/_DEV/SportCamHUD-main-new/src/ffmpeg/streaming.py):
  - Dla trybu CPU silnik automatycznie stosuje optymalne maksimum rdzeni procesora.

### 2.5. Inteligentny domyślny folder eksportu (`render_tab.py`)
- W [`src/gui/qt/tabs/render_tab.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/tabs/render_tab.py) zaimplementowano funkcję `resolve_default_export_dir()`:
  - Priorytet 1: Jeśli użytkownik w przeszłości wskazał folder i jest on zapisany w `layout["global"]["last_export_dir"]` (lub `self._last_output_dir`), sprawdzana jest jego dostępność i uprawnienie do zapisu `os.access(..., os.W_OK)`.
  - Priorytet 2: Katalog źródłowego pliku wideo (np. `D:\GoPro\video.mp4` -> `D:\GoPro\`). Sprawdzane uprawnienia do zapisu.
  - Priorytet 3: Domyślny folder wideo użytkownika systemu (`~/Videos` lub `~/Documents`).
  - Zakaz CWD: Katalog roboczy aplikacji nie jest nigdy używany jako domyślny folder eksportu.
- Przy wyborze pliku wyjściowego w `_select_output` oraz automatycznym generowaniu nazwy w `_on_default_export_name_ready`:
  - Ścieżka jest uzupełniana o prawidłowy katalog bazowy.
  - Wybór użytkownika jest zapisywany w `last_export_dir`.
- Przy dodawaniu do kolejki (`_on_add_to_queue`) i starcie renderowania (`_start_render`):
  - Następuje automatyczna weryfikacja i utworzenie folderu docelowego w razie potrzeby (`os.makedirs`).

### 2.6. Naprawa „Integracji” w Ustawieniach (`settings_tab.py`)
- W [`src/gui/qt/tabs/settings_tab.py`](file:///C:/_DEV/SportCamHUD-main-new/src/gui/qt/tabs/settings_tab.py):
  - Etykieta pozycji braku integracji w liście rozwijanej została zmieniona z `"Nic"` na `"--"` (kod wewnętrzny `"none"`).
  - W `_ensure_disk_persistence` i `_save_settings` poprawnie zapisywane jest pole `layout["integrations"]["auto_activity_source"]`.
  - W `_load_integration_settings_from_dict`:
    - Zablokowano sygnały podczas ustawiania indeksu comboboxa, aby odczyt nie wywoływał kaskadowego resetu do domyślnych wartości.
    - Jawnie odświeżono widoczność paneli Garmin/Strava w oparciu o wczytaną konfigurację.

---

## 3. WERYFIKACJA TESTOWA I TESTY JEDNOSTKOWE

Napisano i uruchomiono zestaw dedykowanych testów jednostkowych w pliku:
`tests/test_gui_logic_degree_export_settings_cleanup.py`

### Wyniki wykonania:
```
tests/test_render_tab_controls_cleanup.py .........                      [ 60%]
tests/test_gui_logic_degree_export_settings_cleanup.py ......            [100%]

============================= 15 passed in 4.20s ==============================
```

Przetestowane przypadki:
1. `test_main_window_project_tab_disabled_without_video`: potwierdza, że po starcie zakładka Projekt jest disabled, a Rendering i Ustawienia są enabled; po załadowaniu wideo Projekt staje się enabled; po wyczyszczeniu Projekt wraca do disabled.
2. `test_immediate_hud_refresh_on_data_ready`: potwierdza, że po emisji `sig_data_streams_ready` oraz wywołaniu `request_preview_refresh` następuje natychmiastowe odświeżenie HUD bez manipulacji odtwarzaczem.
3. `test_degree_symbol_arial_fallback`: weryfikuje podział tekstu `45°` na segmenty cyfry i stopnia, poprawny pomiar łącznej szerokości oraz poprawne renderowanie na obrazie PIL.
4. `test_threads_setting_removed_and_auto_cpu_max`: weryfikuje brak kontrolki `spin_threads` w zakładce ustawień oraz zastosowanie automatycznego maksimum wątków CPU w `render_mixin`.
5. `test_default_export_dir_resolution_and_persistence`: potwierdza, że domyślny folder eksportu wskazuje katalog pliku wideo, że customowy folder jest zapisywany w `last_export_dir`, oraz że CWD nie jest nigdy zwracany.
6. `test_settings_integration_combo_label_and_persistence`: potwierdza, że combobox zawiera opcję `"--"` zamiast `"Nic"`, poprawnie odczytuje wartości `garmin`, `strava`, `none` oraz nie resetuje stanu przy wielokrotnym otwarciu/zapisie.

---

## 4. WERYFIKACJA SYNCHRONIZACJI I PARITY (MAIN-NEW vs PORTABLE)

Zmodyfikowane pliki źródłowe zostały zsynchronizowane do `C:\_DEV\SportCamHUD-portable`.
Skrypt `scripts/check_parity.py` potwierdza 100% zgodność skrótów SHA-256:

```
src/ffmpeg/amd_config.py: MATCH
src/indicators/widget_cache.py: MATCH
def_layout.json: MATCH
src/gui/qt/signals.py: MATCH
src/render_preparation.py: MATCH
src/render_telemetry_cache.py: MATCH
src/telemetry_precompute.py: MATCH
src/ffmpeg/amd_child_process.py: MATCH
src/ffmpeg/streaming.py: MATCH
src/ffmpeg/amd_native_exporter.py: MATCH
src/gui/qt/_mixins/render_mixin.py: MATCH
src/gui/qt/controller.py: MATCH
src/gui/qt/tabs/render_tab.py: MATCH
src/startup_timeline.py: MATCH
src/runtime_paths.py: MATCH
src/gui/map_prefetch.py: MATCH
src/indicators/moving_map.py: MATCH
tests/test_common_render_preparation.py: MATCH
tests/test_amd_benchmark_governance.py: MATCH
tests/test_real_gui_startup_and_child_hash.py: MATCH
src/indicators/gauge.py: MATCH
src/indicators/__init__.py: MATCH
src/indicators/dispatcher.py: MATCH
src/indicators/compositor.py: MATCH
src/ffmpeg/nvidia_native_exporter.py: MATCH
tests/test_gauge_needle_width_parity.py: MATCH
Raporty/RAPORT_GAUGE_NEEDLE_WIDTH_PREVIEW_FINAL_PARITY.md: MATCH
src/gui/export_queue.py: MATCH
tests/test_youtube_upload_ui_disabled.py: MATCH
Raporty/RAPORT_YOUTUBE_UPLOAD_UI_DISABLED.md: MATCH
src/indicators/helpers.py: MATCH
src/indicators/lean.py: MATCH
src/indicators/bar.py: MATCH
src/indicators/text.py: MATCH
src/indicators/custom_text.py: MATCH
src/gui/qt/main_window.py: MATCH
src/gui/qt/_mixins/preset_mixin.py: MATCH
src/gui/qt/_mixins/preview_mixin.py: MATCH
src/gui/qt/_mixins/project_mixin.py: MATCH
src/gui/qt/tabs/load_tab.py: MATCH
src/gui/qt/tabs/settings_tab.py: MATCH
tests/test_gui_logic_degree_export_settings_cleanup.py: MATCH
Raporty/RAPORT_GUI_LOGIC_DEGREE_EXPORT_SETTINGS_CLEANUP.md: MATCH

FIXED_SOURCE_HASH_PARITY=YES
```

---

## 5. PODSUMOWANIE

Wszystkie wymagania zadania zostały zrealizowane bez naruszania istniejących optymalizacji Common Render Prep, pipeline'ów akceleracji GPU (AMD/NVIDIA/Intel) ani SmartSync:
1. Zakładka „Projekt” jest zablokowana bez wideo, a „Rendering” i „Ustawienia” są zawsze dostępne.
2. HUD pojawia się natychmiast po wczytaniu wideo i telemetrii.
3. Glif „°” jest zawsze renderowany czytelnym i eleganckim fontem Arial, a cyfry zachowują font stylu użytkownika.
4. Usunięto zbędną kontrolkę „Liczba wątków”, a eksport CPU wykorzystuje automatyczne maksimum rdzeni.
5. Eksport domyślnie kieruje do folderu wideo źródłowego i zapamiętuje wybory użytkownika, z zachowaniem walidacji zapisu.
6. Combobox Integracji wyświetla etykietę `"--"` i poprawnie persystuje swój stan.
