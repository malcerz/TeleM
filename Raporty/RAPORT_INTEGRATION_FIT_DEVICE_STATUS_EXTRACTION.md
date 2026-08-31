# RAPORT: FIT DEVICE STATUS — BATERIA I TEMPERATURA GARMIN/EDGE

**Data**: 2026-08-31  
**Repo**: `C:\_DEV\TeleM-integration`  
**Branch**: `integration/intel-amd`  
**Commit**: `feb0482`  
**Status**: **PASS**

---

## 1. Cel i zakres zadania

Rozszerzenie parsera FIT oraz modelu telemetrycznego TeleM o obsługę danych **Device Status** z komputerków Garmin / Edge:

1. **Garmin / Edge battery voltage** (`garmin_battery_voltage` [V], domyślnie 2 miejsca po przecinku).
2. **Garmin / Edge battery percentage** (`garmin_battery_percent` [%], domyślnie 0 miejsc po przecinku).
3. **Garmin / Edge device temperature** (`garmin_temperature` [°C], domyślnie 0 miejsc po przecinku).

Wymagania:
- Dostępność danych w: telemetry cache, preview, final export render (wszystkie backendy), liście źródeł wskaźników GUI.
- Semantyka próbek rzadkich: step-hold / last-known (wartości nie zerują się ani nie znikają pomiędzy próbkami co ~1 min).
- Oś czasu: próbki osadzone na kanonicznej absolutnej osi UTC aktywności; brak resetu danych przy przejściach klipów multi-file (014 → 015 → 016).
- Zachowanie izolacji backendów renderujących i nienaruszanie `def_layout.json`.

---

## 2. Audyt pliku FIT (GX010114_116.fit)

Audyt struktury FIT przy użyciu biblioteki `fitparse` wykazał:

* **Typ FIT Message**: Global message `104` (`unknown_104` w standardowym profilu fitparse / `device_status`).
* **Pochodzenie**: Główna jednostka Garmin Edge (`device_index` 0 / device creator).
* **Zdekodowane pola**:
  - `unknown_253` (timestamp): Garmin epoch (`1989-12-31 00:00:00 UTC`).
  - `unknown_0` (battery_voltage): skala mV / 1000.0 = Volts (np. 4172 mV → `4.172 V`).
  - `unknown_2` (battery_level): procent naładowania (np. `91 %`).
  - `unknown_3` (temperature): temperatura urządzenia w stopniach Celsjusza (np. `24 °C`).
* **Liczba rekordów**: Dokładnie **66 rekordów** w `GX010114_116.fit`.
* **Rozpiętość czasowa**:
  - Pierwszy rekord: `2026-08-14 09:40:36 UTC` (4.172 V, 91 %, 24 °C)
  - Ostatni rekord: `2026-08-14 12:01:11 UTC` (4.126 V, 87 %, 35 °C)
* **Częstotliwość**: Próbki pojawiają się w interwałach ok. 1–2 minut.

---

## 3. Zmiany w kodzie

### 3.1 Parser FIT (`telemetry_fit.py`)
- W funkcji `parse_fit()` dodano obsługę wiadomości o nazwie `device_status` lub `unknown_104`.
- Zarejestrowano pola w `field_metadata` z poprawnymi jednostkami (`V`, `%`, `°C`) i etykietami (`Garmin Battery Voltage`, `Garmin Battery Level`, `Garmin Temperature`).
- Zapewniono synchronizację w `sync_fit_to_video()` i utworzenie serii czasowych w obiekcie `FitDataset`.

### 3.2 Resolver & Aliases (`src/telemetry_resolver.py`, `src/ffmpeg/worker_cache.py`, `src/ffmpeg/streaming.py`, `src/ffmpeg/command_builder.py`)
- Zarejestrowano kanoniczne nazwy w `SOURCE_ALIASES["fit"]`:
  - `garmin_battery_voltage` → `("garmin_battery_voltage", "battery_voltage")`
  - `garmin_battery_percent` → `("garmin_battery_percent", "battery_percent", "battery_level")`
  - `garmin_temperature` → `("garmin_temperature", "device_temperature")`
- Zapewniono zgodność wsteczną dla zapytań o `battery` (mapuje na `garmin_battery_percent`) oraz `atemp` (mapuje na `garmin_temperature`).

### 3.3 Interpolarz i Step-Hold (`src/telemetry_extract.py`, `src/telemetry_precompute.py`)
- W `_interpolate_step()` oraz wektorowym `_vectorize_step()` zaimplementowano semantykę *step-hold* z tolerancją 120s przed pierwszym rekordem (zapobiega brakowi wartości na początku nagrania).

### 3.4 Precompute & Domyślne formatowanie (`src/telemetry_precompute.py`, `src/indicators/compositor.py`, `src/gui/telemetry_manager.py`)
- `build_telemetry_cache()` wektoryzuje wartości rzadkich pól FIT przy użyciu `_vectorize_step()`.
- W `compositor.py` i `command_builder.py` ustawiono domyślną precyzję:
  - `garmin_battery_voltage` / jednostka `V` → 2 miejsca po przecinku (np. `4.17 V`),
  - `garmin_battery_percent` / jednostka `%` → 0 miejsc po przecinku (np. `91 %`),
  - `garmin_temperature` / jednostka `°C` → 0 miejsc po przecinku (np. `24 °C`).
- W `src/gui/telemetry_manager.py` zarejestrowano pola do katalogu wskaźników GUI z odpowiednimi zakresami suwaków.

---

## 4. Testy i Walidacja

Utworzono dedykowany zestaw testów automatycznych w `tests/test_fit_device_status.py`:

```text
tests/test_fit_device_status.py::test_fit_device_status_extraction_real_fit PASSED
tests/test_fit_device_status.py::test_sparse_step_hold_interpolation PASSED
tests/test_fit_device_status.py::test_vectorized_step_lookup_parity PASSED
tests/test_fit_device_status.py::test_source_aliases_and_resolver PASSED
tests/test_fit_device_status.py::test_telemetry_precompute_and_formatting PASSED
tests/test_fit_device_status.py::test_multifile_timeline_device_status_continuity PASSED
```

Wynik: **6 passed in 1.54s**

Zweryfikowano:
1. Prawidłową ekstrakcję 66 próbek z kanonicznego pliku `GX010114_116.fit`.
2. Ciągłość wartości pomiędzy rzadkimi próbkami (brak zerowania i brak `None`).
3. Pełną zgodność interpolacji referencyjnej `_interpolate_step` z wektoryzowaną `_vectorize_step`.
4. Ciągłość na osi czasu multi-file przy przejściach klipów 014 → 015 → 016.

---

## 5. Izolacja backendów i bezpieczeństwo

- **Brak zmian w shaderach GPU i potokach enkoderów**: Zmiany nie modyfikują natywnych potoków AMF D3D11, Intel QSV ani NVENC.
- **Brak modyfikacji `def_layout.json`**: Układ domyślny pozostał nienaruszony.
- **Git Safety**: Żadne commity ani push nie zostały wykonane.

---

## 6. Podsumowanie

- **TASK**: Integracja FIT Device Status (bateria i temperatura Garmin/Edge).
- **STATUS**: **PASS**
- **REPORT**: `Raporty/RAPORT_INTEGRATION_FIT_DEVICE_STATUS_EXTRACTION.md`
