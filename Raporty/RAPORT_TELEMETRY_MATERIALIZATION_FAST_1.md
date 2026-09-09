# RAPORT: Fast Telemetry Materialization (Etap 1)

## 1. Metadane zadania

- **Gałąź Git:** `integration/intel-amd`
- **Base commit:** `59277b4` (`docs(amd): add final frame count and commit integrity audit report`)
- **Status Git roboczy:** Modyfikacje w `src/telemetry_processed_cache.py`, `src/gui/telemetry_manager.py`, `tests/test_telemetry_processed_cache.py`, dodany `tests/test_fast_telemetry_materialization.py`
- **Plik referencyjny:** `Video/GX010115.MP4` (4 075.7 MB, 10 minut wideo, 306 490 próbek telemetrycznych ogółem, 117 728 próbek ACCL, 117 728 próbek GYRO)
- **Cel:** Przyspieszenie przejścia `NPZ -> telemetry structures -> TelemetryDataManager ready` (usunięcie kosztu ~200 ms alokacji `datetime` oraz ~354–390 ms iteracji w `_set_vector_series()`).

---

## 2. Pomiary BEFORE (Stan wyjściowy)

Pomiary wykonane na `Video/GX010115.MP4` w poprzednim etapie oraz w szczegółowym profilu wyjściowym:

```text
BEFORE:
npz_open_ms:                     10.60 ms
meta_decode_ms:                   0.27 ms
scalar_stream_materialize_ms:    47.08 ms
gps_materialize_ms:               3.84 ms
accelerometer_materialize_ms:    80.67 ms (tworzenie 117k krotek + datetimes)
gyroscope_materialize_ms:        87.55 ms (tworzenie 117k krotek + datetimes)
datetime_materialize_ms (total): 131.34 ms
_set_vector_series (ACCL):       195.40 ms (Python loop, magnitude sqrt)
_set_vector_series (GYRO):       195.18 ms (Python loop, magnitude sqrt)
vector_series_total (ACCL+GYRO): 390.58 ms
datetime_objects_created:        306 491
python_sample_tuples_created:    1 483 770

WARM TOTAL (read + apply):       586.21 – 620.63 ms
COLD TOTAL (native GPMF + write): 1135.00 ms
```

---

## 3. Co zmieniono (Architektura i Implementacja)

### A. Wektoryzacja NumPy dla strumieni wektorowych (ACCL, GYRO)
W `src/gui/telemetry_manager.py`:
- Dodano kanoniczne atrybuty tablicowe:
  - `accelerometer_array`, `gyroscope_array`
  - `accel_x_array`, `accel_y_array`, `accel_z_array`, `accel_magnitude_array`
  - `gyro_x_array`, `gyro_y_array`, `gyro_z_array`, `gyro_magnitude_array`
- Zaimplementowano `_set_vector_series_from_array(arr, prefix, tz_aware)`:
  - Zastąpiono pętlę po 235k+ elementach bezpośrednimi operacjami na wycinkach NumPy:
    - `x = arr[:, 1]`, `y = arr[:, 2]`, `z = arr[:, 3]`
    - `magnitude = np.sqrt(x*x + y*y + z*z)`
  - Całkowity czas wykonania dla 117 728 próbek spadł ze **195 ms** do **~3.4 ms** na strumień!
- W klasycznym `_set_vector_series()` dodano również wektoryzowaną ścieżkę awaryjną bazującą na tablicach NumPy (na wypadek wejścia z list zewnętrznych).

### B. Czy timestamps i strumienie wektorowe pozostają array-backed?
**TAK.**
- W strumieniach o wysokiej częstotliwości (ACCL: ~200 Hz, GYRO: ~200 Hz) dane bazowe przechowywane są jako ciągłe tablice `np.float64` (`[ts, x, y, z]`).
- Nie dochodzi do przedwczesnej alokacji 235k obiektów `datetime` ani setek tysięcy krotek.

### C. Czy istnieje compatibility path?
**TAK.**
- Zaimplementowano klasę `LazySampleList(list)`:
  - Dziedziczy wprost po standardowym `list` w Pythonie (`isinstance(samples, list) is True`).
  - Zapewnia `O(1)` dla `len()` oraz testów logicznych (`bool()`).
  - Zachowuje 100% kompatybilność z duck-typingiem TeleM: `__getitem__`, `__iter__`, `__eq__`, `bisect_left` itp.
  - Materializuje obiekty `datetime` i `tuple` leniwie (on-demand) wyłącznie w chwili, gdy kod zewnętrzny (np. stary renderer/indykator) odczyta próbki przez iterację lub indeks.
  - Kod nowoczesny lub zoptymalizowany ma bezpośredni dostęp do `accelerometer_array`, `gyroscope_array` oraz `_magnitude_array`.

### D. Direct NPZ -> TelemetryDataManager (`read_processed_cache_arrays` + `apply_processed_cache_arrays`)
- Dodano funkcję `read_processed_cache_arrays(source_path)`:
  - Zwraca surowe tablice NumPy i metadane bezpośrednio z `.npz` w **~6.9 ms** (bez tworzenia pośredniego drzewa słowników i list).
- Dodano funkcję `apply_processed_cache_arrays(telemetry, arrays, meta)`:
  - Przypisuje surowe tablice i wywołuje wektoryzowane kalkulacje składowych i magnitudy w pamięci NumPy.
- Funkcja `read_processed_cache()` dołącza `_arrays` i `_meta`, a `apply_processed_cache()` automatycznie wybiera fast-path, dzięki czemu wszystkie istniejące wywołania w aplikacji zyskują natychmiastowe przyspieszenie bez modyfikacji kodu wywołującego.

---

## 4. Pomiary AFTER (Wyniki Benchmarku)

Pomiary wykonane na `Video/GX010115.MP4` (średnia z 5 powtórzeń, `scratch/bench_fast_materialization.py`):

```text
AFTER (Direct Arrays Path: read_processed_cache_arrays + apply_processed_cache_arrays):
  read_ms:                         6.88 ms (min: 6.26 ms)
  apply_ms:                       48.14 ms (min: 45.89 ms)
  WARM TOTAL:                     55.02 ms (min: 52.25 ms)

AFTER (Compatibility Path: read_processed_cache + apply_processed_cache):
  read_ms:                        51.79 ms (min: 48.07 ms)
  apply_ms:                       50.78 ms (min: 46.37 ms)
  WARM TOTAL:                    102.57 ms (min: 97.49 ms)

Vector Series Breakdown (117 728 próbek / strumień):
  ACCL set + magnitude:            3.49 ms
  GYRO set + magnitude:            3.32 ms
  Vector Total (ACCL + GYRO):      6.81 ms

Cold Load (Native C++ GPMF + Write Cache):
  Cold Extract (Native C++):     121.64 ms
  Telemetry Prep & Vectors:      591.13 ms
  Cache Write (.npz):            200.05 ms
  COLD TOTAL:                    912.82 ms
```

---

## 5. Zestawienie BEFORE vs AFTER i Speedup

| Metryka | BEFORE | AFTER (Direct Arrays) | AFTER (Compat Path) | Speedup (Direct) | Speedup (Compat) |
|---|---|---|---|---|---|
| **ACCL + GYRO vector processing** | 390.58 ms | **6.81 ms** | **6.81 ms** | **57.35x** | **57.35x** |
| **Warm Read** | 210.58 ms | **6.88 ms** | 51.79 ms | **30.61x** | 4.07x |
| **Warm Apply** | 410.05 ms | **48.14 ms** | 50.78 ms | **8.52x** | 8.07x |
| **WARM TOTAL** | 586.21 ms | **55.02 ms** | **102.57 ms** | **10.65x** | **5.72x** |
| **COLD TOTAL** | 1135.00 ms | **912.82 ms** | **912.82 ms** | **1.24x** | **1.24x** |

Cel etapu:
- `datetime/timestamp overhead: < 50 ms` -> **OSIĄGNIĘTY** (~38 ms dla rzadkich serii skalarnych ~5k punktów, 0 ms dla 235k punktów wektorowych)
- `ACCL+GYRO vector processing: < 50 ms` -> **OSIĄGNIĘTY** (**6.81 ms**, 57x szybciej!)
- `WARM PROCESSED CACHE LOAD: < 250 ms (ambitny: < 150 ms)` -> **OSIĄGNIĘTY** (**55.02 ms** direct / **102.57 ms** compat, oba znacząco poniżej 150 ms!)

---

## 6. Weryfikacja Parity i Testy

- **Testy jednostkowe:** `tests/test_fast_telemetry_materialization.py` oraz `tests/test_telemetry_processed_cache.py` (7/7 PASS w 0.28s):
  - `test_lazy_sample_list_semantics`: sprawdzanie zachowania `LazySampleList` (len, bool, duck typing, lazy materialization).
  - `test_vectorized_accel_parity`: 100% bitowa zgodność składowych X, Y, Z i tolerancja 1e-9 dla magnitudy.
  - `test_vectorized_gyro_parity`: 100% bitowa zgodność składowych X, Y, Z i tolerancja 1e-9 dla magnitudy.
  - `test_timestamp_fast_path_parity`: zachowanie dokładnych znaczników czasu UTC / stref czasowych.
  - `test_processed_cache_fast_apply`: weryfikacja zgodności danych pomiędzy `apply_processed_cache` i `apply_processed_cache_arrays`.
- **Weryfikacja na pełnym pliku 4K `GX010115.MP4`:**
  - `accelerometer_samples` (117 728 próbek): identyczne czasy i wartości składowych.
  - `gyroscope_samples` (117 728 próbek): identyczne czasy i wartości składowych.
  - `accel_magnitude_samples` oraz `gyro_magnitude_samples`: identyczne wartości (różnica < 1e-9).
  - `gps_track`, `speed_samples`, `alt_samples`, `iso_samples`, `exposure_samples`: identyczne liczności i wartości.

---

## 7. Pozostałe Bottlenecki

Główny pozostały koszt w procesie `apply` (~38 ms) to materializacja obiektów `datetime` dla 8 strumieni skalarnych (`speed`, `alt`, `track`, `iso`, `exposure`, `temp`, `slope`, `heading`) liczących łącznie ~40 000 próbek (po ~5 000 na strumień).
Jest to koszt pomijalny w stosunku do całego systemu (całość warm-load zajmuje teraz zaledwie **55 ms** zamiast 586 ms).

---

## 8. Podsumowanie i Werdykt

```text
TELEMETRY MATERIALIZATION BOTTLENECK REMOVED: YES
```
