# RAPORT: OPTYMALIZACJA FAZY TELEMETRY_STATES (RATE-AWARE & VECTORIZED)

**Data:** 2026-09-15  
**Backend:** NVIDIA_NATIVE_D3D11 / Shared Telemetry Engine  
**Status:** **CASE A — <5S + PARITY PASS (COMPLETE)**  

---

## 1. Cel i Zakres Zadania

Przyspieszenie fazy `telemetry_states` podczas przygotowania HUD (`Przygotowanie HUD — Telemetria klatek`).
Przed optymalizacją faza ta trwała **~34.23 s** dla projektu 3-plikowego (63 391 klatek, ~98.9% całego czasu HUD preparation) z powodu wykonywania w każdej klatce sekwencji 13 skalarnych wywołań resolvera telemetrycznego Python, operacji `bisect_right` oraz formatowania `strftime`.

Wymagania:
1. **Active-Only:** Ewaluacja wyłącznie kanałów potrzebnych dla aktywnych wskaźników (`enabled=True`), całkowite pominięcie wskaźników wyłączonych.
2. **Rate-Aware & Vectorized:** Podział kanałów według ich rzeczywistej dynamiki źródłowej (~1 Hz, wolne/rzadkie, zegar) i jednorazowe przemapowanie całej osi czasu za pomocą wektorowych operacji NumPy (`np.interp`, `np.searchsorted`, wektoryzowany model baterii).
3. **Integer-Only Fields:** Pola HR, Cadence, Power, ISO, Exposure formatowane bez części dziesiętnej, bez utraty precyzji w wewnętrznych tablicach float.
4. **Zero-Regression Parity:** 100% zgodności na próbie 1000 klatek, klatce 0, granicach klipów 1/2 i 2/3 oraz ostatniej klatce ($|\Delta| \le 10^{-6}$ dla floatów, identyczność bajtowa dla stringów).
5. **Battery Continuity:** Zachowanie ciągłości modelu baterii Garmin na złączonej osi czasu projektu bez skoków na granicach klipów.
6. **Progress Tracking:** Zachowanie aktualizacji paska postępu w chunkach (`Przygotowanie HUD — X% · Telemetria klatek ...`).

---

## 2. Audyt Stanu Początkowego (Before)

### A. Audyt Aktywnych i Nieaktywnych Wskaźników Layoutu
- **Całkowita liczba wskaźników w `def_layout.json`:** 30
- **Aktywne wskaźniki (`enabled=True`):** 14
  - `time_display` (form: time_display)
  - `track_map` (form: map)
  - `fit_heart_rate_text` (form: chart, field: heart_rate)
  - `fit_cadence_text` (form: chart, field: cadence)
  - `fit_distance_text` (form: bar, field: distance)
  - `speed_text` (form: gauge)
  - `exposure_text` (form: text)
  - `alt_text` (form: bar)
  - `fit_curVpower_text` (form: bar)
  - `fit_solar_text` (form: bar)
  - `fit_garmin_battery_percent_text` (form: segment_bar)
  - `iso_text` (form: text)
  - `fit_gopro_battery_text` (form: text)
  - `temp_text` (form: text)
- **Nieaktywne wskaźniki (`enabled=False`):** 16 (`fit_K1_text`, `fit_K2_text`, `fit_enhanced_altitude_text`, `fit_enhanced_speed_text`, `fit_fractional_cadence_text`, `fit_temperature_text`, `fit_passing_speed_text`, `fit_passing_speedabs_text`, `fit_radar_current_text`, `fit_battery_pct_2_1_text`, `fit_battery_pct_3_2_text`, `fit_discharge_text`, `fit_solar_pct_text`, `fit_garmin_battery_voltage_text`, `fit_garmin_temperature_text`, `fit_battery_pct_text`).

**Czy nieaktywne wskaźniki były liczone w pętli?**
- `nvidia_native_exporter.py` rozwiązywał na sztywno zestaw 13 pól per klatka. Wewnątrz `telemetry.resolve_value("distance", ...)` funkcja `resolve_distance_samples` i `_is_usable_cumulative_distance` wykonywały walidację całej serii od nowa w każdej klatce (134.4 miliona wywołań `math.isfinite`).

### B. Profil Hot-Path Baseline (cProfile, 63 391 klatek)
- **Czas całkowity baseline (cProfile):** 51.744 s
- **Liczba wywołań funkcji:** 217 599 400
- **Główne wąskie gardła:**
  1. `_is_usable_cumulative_distance` & `math.isfinite`: 25.88 s (50.0% czasu całkowitego, 134.46 mln wywołań)
  2. `telemetry.resolve_value`: 49.62 s skumulowanego czasu (760 692 wywołania)
  3. `resolve_current_presentation`: 19.36 s (443 737 wywołań)
  4. `_bisect.bisect_right`: 3.09 s (1 077 445 wywołań)
  5. `datetime.strftime`: 0.44 s (126 782 wywołania)

---

## 3. Zastosowana Implementacja

Utworzono dedykowany, zoptymalizowany moduł [`src/telemetry_states_fast.py`](file:///H:/_Dev/BikeRideHUD/src/telemetry_states_fast.py):

### A. Wektoryzacja Osi Czasu i Przeliczania Znaczników
1. Wygenerowanie tablicy indeksów klatek i sekund globalnych: `frame_indices = np.arange(export_frames)`, `t_global = frame_indices / fps`.
2. Zmapowanie sekund złączonej osi czasu na sekundy względne wobec `base_dt` z mikroprocesową precyzją `np.round((local_s - clip.local_start_s) * 1e6) / 1e6` (identycznie jak Python `datetime.timedelta`).

### B. Klasyfikacja i Wektoryzacja Kanałów Telemetrycznych
- **Gęste kanały ciągłe (~1 Hz, interpolacja liniowa):**
  - `speed`, `curVpower`, `distance`, `altitude`, `solar_percent`, `temperature`, `gopro_battery_percent`, `GPS track (lat/lon)`.
  - Wyciągnięcie serii FIT raz jako tablic `(ts_rel, values)` typu float64.
  - Wektoryzacja w 1 operacji `np.interp(frame_rel_s, ts_rel, values, left=..., right=values[-1])`.
- **Kanały dyskretne / schodkowe (~1 Hz, forward-fill):**
  - `heart_rate`, `cadence`, `iso`, `exposure`.
  - Wektoryzacja w 1 operacji `idx = np.searchsorted(ts_rel, frame_rel_s, side='right') - 1`.
- **Rzadkie kanały monotoniczne (Garmin Battery, 28 próbek na 35 min):**
  - Wektorowe zmapowanie `ActiveTimeMapper._active_starts` i `_active_ends` przez `np.searchsorted` -> wyznaczenie aktywnych sekund dla 63 391 klatek w <0.001 s.
  - Wyznaczenie liniowego trendu rozładowania `seg.start_value + slope * active_sec`.

### C. Zoptymalizowane Formatowanie Stringów i Alokacja C-Struct
1. Alokacja pojedynczej ciągłej tablicy struktur C: `(TelemFrameState * export_frames)()`.
2. Formatowanie daty i godziny (`strftime`) wyłącznie przy zmianie pełnej sekundy (raz na ~30 klatek zamiast 63 391 razy).
3. Bezpośrednie formatowanie liczb całkowitych dla pól integer-only (HR, Cadence, Power, ISO, Exposure) oraz sformatowanych floatów dla prędkości, dystansu, wysokości, temperatury i baterii.
4. Przekazywanie tablicy ctypes bezpośrednio do `dll.telem_nvenc_set_telemetry(handle, c_states, export_frames)` bez alokacji i rozpakowywania obiektów Python.

---

## 4. Pomiary Wydajności i Benchmark

### Środowisko Testowe:
- **Projekt:** `Video/GX010290.MP4`, `Video/GX010291.mp4`, `Video/GX020291.mp4` + `Video/20260911.fit`
- **Layout:** `def_layout.json` (3840x2160)
- **Liczba klatek:** 63 391 klatek @ 29.970 fps (2115.15 s osi czasu)

### Wyniki Benchmarku:
```text
BEFORE (Legacy Scalar Resolver):  34.23 s
AFTER Run 1:                      0.4217 s
AFTER Run 2:                      0.4167 s
AFTER Run 3:                      0.4162 s
AFTER Median:                     0.4167 s
----------------------------------------------------------------------
SPEEDUP:                          82.14x faster
CZAS NA KLATKĘ:                   0.006574 ms/frame (6.574 µs/frame)
KLASYFIKACJA:                     CASE A (<5 s + 100% PARITY PASS)
```

### Profil Hot-Path After (cProfile):
- **Czas wykonania pod cProfile:** 0.6338 s (wobec 51.744 s baseline)
- `resolve_value` calls: **0** (poprzednio 760 692)
- `math.isfinite` calls: **21 240** (poprzednio 134 466 157)
- `_bisect.bisect_right` calls: **0** (poprzednio 1 077 445)

---

## 5. Weryfikacja Zgodności (Parity Validation)

Testy porównawcze OLD vs NEW wykonano na **1008 klatkach** (klatka 0, 1000 równomiernie rozłożonych klatek w całym filmie, granice klipów `b1_2 ± 2` i `b2_3 ± 2`, ostatnia klatka 63 390):

### Kanały Float ($|\Delta| \le 10^{-6}$):
| Pole Telemetryczne | Max Abs Diff | Mean Abs Error (MAE) | Status |
| :--- | :--- | :--- | :--- |
| `speed_kmh` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `heart_rate_bpm` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `cadence_rpm` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `power_w` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `distance_km` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `altitude_m` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `solar_pct` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `garmin_battery_pct` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `gopro_battery_pct` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `temperature_c` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `iso` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `exposure_denom` | 0.00000000e+00 | 0.00000000e+00 | **PASS** |
| `map_latitude` | 8.36308800e-12 | 1.83401250e-12 | **PASS** |
| `map_longitude` | 1.15996102e-11 | 2.54011830e-12 | **PASS** |

### Kanały Prezentacji Tekstowej (Identyczność Bajtowa):
| Pole Tekstowe | Sprawdzonych Klatek | Niezgodności | Status |
| :--- | :--- | :--- | :--- |
| `speed_str` | 1008 | 0 | **PASS** |
| `hr_str` | 1008 | 0 | **PASS** |
| `cad_str` | 1008 | 0 | **PASS** |
| `power_str` | 1008 | 0 | **PASS** |
| `distance_str` | 1008 | 0 | **PASS** |
| `altitude_str` | 1008 | 0 | **PASS** |
| `solar_str` | 1008 | 0 | **PASS** |
| `garmin_battery_str` | 1008 | 0 | **PASS** |
| `gopro_battery_str` | 1008 | 0 | **PASS** |
| `temp_str` | 1008 | 0 | **PASS** |
| `iso_str` | 1008 | 0 | **PASS** |
| `exposure_str` | 1008 | 0 | **PASS** |
| `time_display_date` | 1008 | 0 | **PASS** |
| `time_display_time` | 1008 | 0 | **PASS** |
| `time_display_elapsed` | 1008 | 0 | **PASS** |

**Łączna liczba błędów parzystości:** **0 / 1008 klatek (100% PARITY PASS)**.

---

## 6. Ciągłość Granic Baterii (Battery Boundary Continuity)

Zweryfikowano zachowanie wartości baterii Garmin na złączeniach klipów na złączonej osi czasu (`VideoTimeline`):

```text
CLIP 1 -> CLIP 2 (wokół klatki 4596, t=153.35 s):
  - Klatka 4595: t=153.320 s | bat=68.8993% | str=68.9
  - Klatka 4596: t=153.353 s | bat=68.8982% | str=68.9
  - Klatka 4597: t=153.387 s | bat=68.8982% | str=68.9
  Deltas: d(f, f-1) = -0.001022%, d(f+1, f) = -0.000015% (brak skoku luki zegarowej)

CLIP 2 -> CLIP 3 (wokół klatki 54516, t=1819.02 s):
  - Klatka 54515: t=1818.984 s | bat=67.8014% | str=67.8
  - Klatka 54516: t=1819.017 s | bat=67.8013% | str=67.8
  - Klatka 54517: t=1819.051 s | bat=67.8013% | str=67.8
  Deltas: d(f, f-1) = -0.000038%, d(f+1, f) = -0.000023% (brak skoku luki zegarowej)
```

---

## 7. Izolacja Backendów i Zmodyfikowane Pliki

- **Zmienione pliki:**
  1. [`src/telemetry_states_fast.py`](file:///H:/_Dev/BikeRideHUD/src/telemetry_states_fast.py) *(Nowy moduł: wektorowa prekomputacja stanów telemetrycznych)*
  2. [`src/ffmpeg/nvidia_native_exporter.py`](file:///H:/_Dev/BikeRideHUD/src/ffmpeg/nvidia_native_exporter.py) *(Zastąpienie skalarnej pętli przez `compute_fast_telemetry_states`)*
  3. [`tests/test_telemetry_states_rate_aware.py`](file:///H:/_Dev/BikeRideHUD/tests/test_telemetry_states_rate_aware.py) *(Nowe testy jednostkowe i integracyjne)*
- **Pliki nienaruszone:**
  - Kod AMD, Intel, D3D11 Compositor, koder NVENC/AMF, layout parser, render preview, audio slice, polityka zaokrągleń i formatowania liczb.

---

## 8. Wykaz Artefaktów w `scratch/telemetry_states_rate_aware/`

- `hotpath_before.txt` (4 399 bajtów) — Szczegółowy profil cProfile przed zmianami
- `active_indicator_audit.txt` (3 897 bajtów) — Zestawienie 14 aktywnych i 16 nieaktywnych wskaźników
- `field_rate_audit.txt` (5 144 bajtów) — Klasyfikacja częstotliwości próbkowania i strategie ewaluacji
- `hotpath_after.txt` (5 003 bajtów) — Profil cProfile po wektoryzacji
- `benchmark.txt` (914 bajtów) — Pomiary 3 przejść benchmarku i przyspieszenia
- `parity.txt` (2 843 bajtów) — Raport dokładności 1008 klatek testowych
- `battery_boundary.txt` (1 303 bajtów) — Raport ciągłości baterii na granicach klipów
- `test.log` (330 bajtów) — Podsumowanie testów
- `artifacts_manifest.txt` (610 bajtów) — Manifest artefaktów
- `ntfy_result.txt` (590 bajtów) — Potwierdzenie wysyłki powiadomienia NTFY

---

## 9. Podsumowanie NTFY Gate

Powiadomienie zostało wysłane i odebrane:
- **Treść:** `BikeRideHUD telemetry rate-aware: CASE A — <5S + PARITY PASS, before=34.23s, after=0.42s, speedup=82.1x.`
- **Status:** `200 OK (Attempt 1/3)`
