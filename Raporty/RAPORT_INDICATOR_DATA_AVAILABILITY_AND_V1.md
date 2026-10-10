# RAPORT: Automatyczne ukrywanie wskaźników bez danych + Wersja 1.0

## 1. Cel i zakres zmian

W wersji produkcyjnej materiał wideo bez określonych strumieni telemetrii (np. DJI zawierający wyłącznie IMU/metadane kamery bez zewnętrznego FIT/GPX lub GoPro bez sensorów FIT) wyświetlał na HUD wskaźniki bez danych w postaci placeholderów:
- `--`
- `0`
- `-- %`
- `-- BPM`
- `-- RPM`
- puste wykresy lub puste podziałki linijek.

Dodatkowo, wersja aplikacji została oficjalnie podbita do:
**SportCamHUD v1.0** (zarówno w oknie aplikacji: `APP_TITLE v1.0`, jak i w `pyproject.toml`).

---

## 2. Architektura i kluczowe zasady

### 2.1. Rozróżnienie Przypadek A vs Przypadek B
Zaimplementowano ścisłe rozróżnienie:
- **Przypadek A (Brak źródła na poziomie projektu):**
  Jeżeli dla danego projektu dane źródło w ogóle nie istnieje (np. brak pliku FIT, brak streamu GPS w GPMF, brak sensora tętna/kadencji), wskaźnik jest **całkowicie niewidoczny**.
  - **Zero Placeholder Leak:** Nie jest renderowane tło, ramka, etykieta, jednostka, ikona ani znak `--`.
  - Wskaźnik nie rejestruje bounding boxa (`_bboxes`) i nie generuje dirty rectów ani kompozycji atlasów.
- **Przypadek B (Chwilowa luka danych w klatce):**
  Jeżeli źródło danych istnieje w projekcie, ale w danej klatce pomiarowej wartość wynosi `None` (np. chwilowy zanik sygnału GPS lub przerwa w nadawaniu czujnika), wskaźnik pozostaje widoczny i wyświetla standardowy placeholder `--`.

### 2.2. Nienaruszalność layoutu i presetów (Non-destructive)
- Flaga `enabled` w presetach i plikach JSON (`def_layout.json`, presety użytkownika) **nigdy nie jest mutowana** na `False`.
- Widoczność efektywna wynosi:
  $$\text{effective\_visible} = \text{user\_enabled} \land \text{data\_available}$$
- `_indicator_availability` jest polem czysto runtime'owym i jest automatycznie usuwane przy zapisie (`normalize_layout_for_save`).
- Jeżeli użytkownik w trakcie pracy dołączy plik FIT/GPX, dostępność jest natychmiast przeliczana i wskaźniki automatycznie stają się widoczne.

### 2.3. Ręczny wybór źródła vs `source="auto"`
- **Źródło jawnie wybrane (FIT, GPX, GPMF, camera):** Dostępność jest weryfikowana ściśle dla wybranego źródła. Jeśli użytkownik wybrał `source="fit"`, a w projekcie jest tylko GPMF, wskaźnik jest ukrywany (brak nieautoryzowanego fallbacku).
- **Źródło automatyczne (`source="auto"` lub puste):** Sprawdzana jest lista kandydatów w kolejności kanonicznej:
  - Tętno / Kadencja / Moc / Bateria czujników: `["fit", "gpx"]`
  - Prędkość / Dystans / Wysokość / Nachylenie: `["gpmf", "fit", "gpx"]` (dla dystansu preferencja FIT -> GPMF -> GPX)
  - Parametry kamery (ISO, Exposure): `["gpmf", "camera"]`
  - Mapa trasy (`track_map`): `["fit", "gpmf", "gpx"]`

### 2.4. Specyfika kamer (DJI, GoPro)
- **DJI:** IMU, żyroskop, akcelerometr, kąt pochylenia (lean) -> `SHOW`. Brak GPS/FIT -> prędkość, dystans, wysokość, mapa, tętno, kadencja, bateria -> `HIDE`.
- **GoPro GPMF:** Prędkość, wysokość, mapa GPS, ISO, ekspozycja -> `SHOW`. Tętno, kadencja (bez FIT) -> `HIDE`. Po dołączeniu FIT -> natychmiastowy powrót do `SHOW`.
- **Dynamiczne pola FIT (`fit_*_text`):** Sprawdzana jest obecność pola w `available_fit_fields` oraz istnienie próbek w `fit_data`. Brak pola -> `HIDE`.

---

## 3. Zmodyfikowane moduły

1. **`src/indicators/availability.py` (Nowy centralny silnik):**
   - `indicator_data_available(key, ind_cfg, telemetry, **kwargs) -> tuple[bool, str]`
   - `compute_indicator_availability(layout, telemetry, **kwargs) -> dict[str, tuple[bool, str]]`
   - `get_effective_indicator_availability(layout, telemetry, **kwargs) -> dict[str, bool]`
   - `log_indicator_availability(availability_results)`
2. **`src/indicators/compositor.py`:**
   - Obsługa parametru `indicator_availability` w `compose_overlay()` i `render_preview()`.
   - Wczesne pomijanie wskaźnika (`continue`) bez rejestracji bounding boxa przy `not indicator_availability[key]`.
   - Obsługa `time_display` pod kątem dostępności.
   - Oczyszczanie `_indicator_availability` w `normalize_layout_for_save()`.
3. **`src/indicators/frame_data.py`:**
   - Przekazywanie `indicator_availability` w słowniku `prepare_overlay_frame_data()`.
4. **`src/indicators/moving_map.py`:**
   - Sprawdzanie `_indicator_availability` w `render_map_working_image()` oraz `render_map_unrotated_working_image()`.
5. **`src/telemetry_precompute.py`:**
   - Przechowywanie `indicator_availability` w strukturze `_Static` cache'a telemetrii.
6. **`src/gui/qt/_mixins/project_mixin.py` & `preset_mixin.py` & `controller.py`:**
   - Automatyczne przeliczanie dostępności i emitowanie logu po załadowaniu projektu, zmianie telemetrii lub wczytaniu presetu.
7. **`src/gui/qt/_mixins/preview_mixin.py`:**
   - Przekazywanie `indicator_availability` do podglądu wideo (w tym podglądu bez telemetrii).
8. **Parzystość eksporterów GPU:**
   - `src/ffmpeg/amd_native_exporter.py`: weryfikacja dostępności mapy w `_map_gpu_layout_safe`, `_amd_layout_roles` oraz preloadzie kafelków.
   - `src/ffmpeg/intel_native_exporter.py`: weryfikacja w `_compute_layout_widget_boxes` i eksporcie GPU mapy.
   - `src/ffmpeg/nvidia_native_exporter.py`: filtracja deskryptorów w `build_canonical_indicators()` i `build_map_indicator_desc()`.
9. **Podbicie wersji do 1.0:**
   - `src/gui/qt/main_window.py`: `APP_VERSION = "1.0"` (Tytuł: `SportCamHUD v1.0`).
   - `pyproject.toml`: `version = "1.0"`.

---

## 4. Log diagnostyczny

Po wczytaniu danych emitowany jest kanoniczny raport:
```text
[INDICATOR AVAILABILITY] key=alt_text visible=False reason="no source available (configured=auto, candidates=['gpmf', 'fit', 'gpx'])"
[INDICATOR AVAILABILITY] key=fit_cadence_text visible=False reason="no source available (configured=auto, candidates=('fit', 'gpx'))"
[INDICATOR AVAILABILITY] key=fit_heart_rate_text visible=False reason="no source available (configured=auto, candidates=('fit', 'gpx'))"
[INDICATOR AVAILABILITY] key=lean_indicator visible=True reason="source=imu"
[INDICATOR AVAILABILITY] key=speed_text visible=True reason="source=gpmf"
[INDICATOR AVAILABILITY] key=track_map visible=True reason="source=gpmf"
```

---

## 5. Weryfikacja testowa

Utworzono dedykowany zestaw testów `tests/test_indicator_availability.py` pokrywający:
- DJI bez FIT: widoczne IMU/lean, ukryte HR, Cadence, Garmin battery, Solar, Speed, Alt, Map.
- DJI z FIT: automatyczne pojawienie się wskaźników z danymi FIT.
- GoPro bez FIT: widoczne prędkość, wysokość, ISO, ekspozycja, mapa; ukryte HR/kadencja.
- Wybór ręczny `source="fit"` bez fallbacku do GPMF -> HIDE.
- Dynamiczne pola FIT (`fit_*_text`) weryfikujące `available_fit_fields`.
- Brak wycieku graficznego (zero placeholder leak) w `compose_overlay`.
- Przypadek A (brak strumienia) vs Przypadek B (chwilowe `None` w klatce).
- Parzystość deskryptorów NVIDIA i bounding boxów Intel.
- Podbicie wersji do 1.0.

Wynik testów:
```
tests/test_indicator_availability.py::test_app_version_is_v1 PASSED
tests/test_indicator_availability.py::test_dji_without_fit_telemetry_availability PASSED
tests/test_indicator_availability.py::test_dji_with_fit_telemetry_availability PASSED
tests/test_indicator_availability.py::test_gopro_without_fit_availability PASSED
tests/test_indicator_availability.py::test_explicit_source_selection_no_fallback PASSED
tests/test_indicator_availability.py::test_dynamic_fit_fields_availability PASSED
tests/test_indicator_availability.py::test_compositor_zero_placeholder_leak_for_hidden_indicators PASSED
tests/test_indicator_availability.py::test_case_a_vs_case_b PASSED
tests/test_indicator_availability.py::test_nvidia_and_intel_exporters_parity PASSED

============================== 9 passed in 0.91s ==============================
```

Zsynchronizowano pełny zestaw zmian z repozytorium portable: `C:\_DEV\SportCamHUD-portable`.
