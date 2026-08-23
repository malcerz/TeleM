# RAPORT: ETAP 10K — FIT GUI / Dynamic Fields / Ruler Scale Bugfix

**Data wykonania:** 2026-08-22  
**Autor:** Antigravity  
**Stan:** **DYNAMIC FIT GUI: FIXED**

---

## 1. Cel etapu

Celem ETAPU 10K była pełna diagnostyka i naprawa ścieżki dynamicznych pól FIT w GUI TeleM:
1. **Dynamiczne pola FIT:** Poprawienie dodawania i wyświetlania pól:
   - `Temperature` (FIT)
   - `Solar` (FIT)
   - `Solar Pct` (FIT)
   - `Power / curVpower` (FIT)
   - `Battery` (FIT)
   - `Battery Pct` (FIT)
2. **Stable Field Identity / Developer Fields:** Prawidłowa tożsamość i obsługa pól deweloperskich FIT o takich samych nazwach (`battery_pct` z dev_idx 2 vs dev_idx 3) bez nadpisywania w parserze.
3. **GUI Stream Discovery & Indicator Creation:** Przywrócenie spójnych etykiet (`display_name`), jednostek (`unit`) i sugerowanych form (`suggested_form`) z metadanych FIT, unikanie raw key names (`fit_*_text`).
4. **GUI Size Constraint:** Zwiększenie maksymalnego rozmiaru widgetów w GUI (`size` / `map_size`) z 50.0 do 100.0 (wsparcie rozmiarów 75, 100).
5. **Ruler Major Step:** Wprowadzenie obsługi `major_step` w linijkach (`Distance -> 1.0 km`, `Temperature -> 1.0 °C`) z pierwszeństwem jawnej konfiguracji użytkownika.
6. **Telemetry Availability:** Poprawne traktowanie wartości `None` / brakujących próbek na początku aktywności (np. `solar_pct`) poprzez renderowanie placeholdera (`"--"`) zamiast ukrywania całego widgetu w podglądzie.

---

## 2. Diagnoza Root Cause

1. **Nadpisywanie Developer Fields w `telemetry_fit.py`:**
   - W pliku `Jazda_na_rowerze_w_porze_lunchu.fit` istnieją dwa pola `battery_pct`:
     - `dev_data_index=2, field_definition_number=1` (2340 próbek)
     - `dev_data_index=3, field_definition_number=2` (4299 próbek)
   - Parser zapisywał wartości do słownika `raw[field.name] = field.value`, przez co drugie pole bezwarunkowo nadpisywało pierwsze.
2. **Ukrywanie wskaźników z `value is None` w `compositor.py`:**
   - `solar_pct` pojawia się w aktywności dopiero po 1h 38m (od `11:18:01`).
   - W `compositor.py` warunek `if value is None: continue` powodował całkowite pominięcie renderowania widgetu przy `t=0`, sprawiając wrażenie, że kliknięcie przycisku w GUI nic nie robi.
3. **Brak etykiet i jednostek przy tworzeniu wskaźników FIT:**
   - `_create_indicator` w `indicator_mixin.py` ustawiało domyślne `label = key` (np. `"fit_temperature_text"`) oraz `unit = ""`.
   - `_discover_data_streams` nie przekazywało sugerowanych form ani metadanych jednostek dla developer fields.
4. **Ograniczenie `size` do 50.0:**
   - W `src/gui/indicator_schemas.py` i `src/gui/qt/models.py` pole `size` miało `max_val=50.0`.
5. **Sztywna liczba kresek w Ruler Bar:**
   - `_render_ruler` w `src/indicators/bar.py` dzielił podziałkę według stałej liczby kresek `major_ticks`, ignorując jednostki danych (`km`, `°C`).

---

## 3. Zastosowane rozwiązania

### A. Parser i tożsamość pól FIT (`telemetry_fit.py`)
- Skanowanie definicji pól deweloperskich (`field_description`) oraz ich wystąpień w komunikatach `record`.
- Dla pól o unikalnych nazwach zachowano oryginalne klucze (`curVpower`, `solar_pct`, `solar`, `battery`, `discharge`, `K1`, `K2`).
- Dla kolizji nazw utworzono stabilne, unikalne tożsamości:
  - `battery_pct_2_1` (`display_name="Battery Pct [Dev 2:1]"`, 2340 próbek)
  - `battery_pct_3_2` (`display_name="Battery Pct [Dev 3:2]"`, 4299 próbek)
  - Alias wsteczny `battery_pct -> battery_pct_3_2` dla pełnej zgodności z istniejącymi presetami (m.in. `cycling_dashboard_v10.json`).
- Obiekty `FitRecords` i `FitDataset` przechowują pełny katalog metadanych `field_catalog` (`display_name`, `unit`, `is_dev`, `dev_data_index`, `field_def_num`, `samples`, `occurred`).

### B. GUI Stream Discovery & Add Indicator (`indicator_mixin.py`, `telemetry_manager.py`)
- W `_discover_data_streams()` strumienie pobierają jednostki i czytelne nazwy bezpośrednio z `field_catalog`.
- W `_create_indicator()` dla kluczy `fit_*_text`:
  - `label` ustawiany na przyjazną nazwę (np. `"Temperature"`, `"Solar"`, `"Solar Pct"`, `"CurVpower"`).
  - `unit` ustawiany na poprawną jednostkę (np. `"°C"`, `"%"`, `"W"`).
  - `major_step` ustawiany na `1.0` dla temperatury i dystansu.
- W `_on_stream_clicked()` dodano inwalidację `self._chart_data_cache = None` oraz `self._prepare_cache.clear()`, co gwarantuje natychmiastowe przeliczenie wykresów i wartości po dodaniu nowego strumienia.

### C. Zwiększenie limitu rozmiaru GUI do 100.0
- W `src/gui/indicator_schemas.py`: `size` i `map_size` podniesione do `100.0`.
- W `src/gui/qt/models.py`: `_header_fields` `max_val` podniesione z 50.0 do `100.0`.

### D. Ruler `major_step` (`src/indicators/bar.py`, `src/gui/qt/models.py`)
- Dodano pole `major_step` do schematu `Ticks` w `models.py`.
- W `_render_ruler()`:
  - Jeśli `major_step` jest podany w konfiguracji, podziałka wyliczana jest ze wzoru: `major_divisions = max(1, round(range_span / major_step))`.
  - W przeciwnym razie domyślny `major_step = 1.0` jest automatycznie dedukowany dla `km` oraz `°C`.
  - Wartość użytkownika ma bezwzględne pierwszeństwo.

### E. Bezpieczne renderowanie brakujących próbek (`compositor.py`)
- Usunięto warunek pomijający wskaźniki z `value is None` w `compose_overlay`. Wskaźniki z brakującą wartością (np. `solar_pct` na początku filmu) renderują się poprawnie z etykietą i wartością `"--"`, umożliwiając ich edycję, przesuwanie i skalowanie w GUI.

---

## 4. Wyniki weryfikacji i testów

### A. Testy jednostkowe (`tests/test_etap10k_fit_gui.py`)
```text
tests/test_etap10k_fit_gui.py .......                                    [100%]
============================= 7 passed in 11.21s ==============================
```
Weryfikowane przypadki:
1. `test_fit_parser_developer_field_identities` — unikalne tożsamości developer fields, brak kolizji `battery_pct`.
2. `test_fit_sync_and_dataset` — synchronizacja wszystkich pól FIT do `FitDataset`.
3. `test_gui_stream_discovery` — wykrywanie wszystkich strumieni z poprawnymi jednostkami (`°C`, `W`, `%`).
4. `test_gui_add_indicator_defaults` — tworzenie wskaźników z przyjaznymi etykietami i jednostkami.
5. `test_gui_size_limit_100` — walidacja limitów rozmiaru do 100.0 w schematach.
6. `test_major_step_ruler` — podziałka główna dla dystansu (1 km), temperatury (1 °C) i jawnego override.
7. `test_overlay_rendering_with_added_fit_indicators` — pełny render nakładki z dodanymi wskaźnikami FIT.

### B. Testy regresyjne poprzednich etapów
```text
tests/test_battery_solar_optimization.py ......                          [ 35%]
tests/test_distance_optimization.py ......                               [ 70%]
tests/test_time_display_optimization.py .....                            [100%]
============================= 17 passed in 0.89s ==============================
```

---

## 5. Zgodność z AGENTS.md

- **Zachowano:**
  - `presets/cycling_dashboard_v10.json` (brak zmian).
  - Pipeline CPU, AMD, NVIDIA, Map, SmartSync, FFmpeg.
  - Wsteczna kompatybilność zapytań `fit_battery_pct_text` / `battery_pct`.
- **Zmieniono:**
  - `telemetry_fit.py`
  - `src/gui/telemetry_manager.py`
  - `src/gui/indicator_schemas.py`
  - `src/gui/qt/models.py`
  - `src/gui/qt/_mixins/indicator_mixin.py`
  - `src/indicators/bar.py`
  - `src/indicators/compositor.py`
- **Testowano:**
  - Środowisko Python 3.14 / pytest na Windows z plikami testowymi `Video/GX010115.MP4` i `Video/Jazda_na_rowerze_w_porze_lunchu.fit`.
- **Nie testowano:**
  - NVIDIA hardware-specific paths (niedostępne na maszynie AMD).

---

## 6. Decyzja końcowa

**DYNAMIC FIT GUI: FIXED**
