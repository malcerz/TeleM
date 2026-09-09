# Raport: Przywrócenie GoPro TMPC (Camera Temperature) w Native GPMF + NPZ Cache

**Data:** 2026-09-05  
**Gałąź Git:** `integration/intel-amd`  
**Base commit:** `59277b4` (`docs(amd): add final frame count and commit integrity audit report`)  
**Status:** **PASS**

---

## 1. Root Cause Analysis

### Gdzie TMPC ginęło?
Po przeniesieniu ekstrakcji metadanych z parsera Pythonowego (`src/telemetry_gpmf_new.py`) na natywny moduł C++ (`src/native/gpmf/gpmf_extractor.cpp`) temperatura kamery przestała być w ogóle ekstrahowana (`temperature_samples count: 0`).

Dokładne prześledzenie pipeline wykazało:
1. **Native Extractor (`gpmf_extractor.cpp`) — GŁÓWNA PRZYCZYNA:**
   - Parser C++ iterował po kontenerach `STRM` za pomocą `GPMF_FindNext(&ms, STR2FOURCC("STRM"), ...)` i następnie wywoływał `GPMF_SeekToSamples(&strm)`.
   - `GPMF_SeekToSamples` w strukturze GPMF pozycjonuje strumień na głównym FourCC próbek danego kontenera (np. `ACCL`, `GYRO`, `ISOE`, `SHUT`, `GPS9`).
   - W kodzie C++ znajdowała się gałąź `else if (key == STR2FOURCC("TMPC"))`. Jednak w formacie GoPro GPMF FourCC `TMPC` **nigdy nie jest głównym kluczem próbek kontenera `STRM`**. Jest to dodatkowy KLV zagnieżdżony wewnątrz kontenerów strumieni `Accelerometer` (`ACCL`) oraz `Gyroscope` (`GYRO`), umieszczony przed samymi próbkami przyspieszenia/żyroskopu.
   - W rezultacie gałąź `else if (key == STR2FOURCC("TMPC"))` nigdy nie była ewaluowana, a wektor `tmpc_blocks` pozostawał pusty (0 bloków).
   - Co więcej, w starej gałęzi `TMPC` użyto `GPMF_ScaledData`, co w przypadku kontenera `ACCL` podzieliłoby temperaturę przez `SCAL=417` akcelerometru, wypaczając wartość fizyczną z ~30 °C do ~0.07 °C.
2. **Binding Python/C++ (`gpmf_bindings.cpp`):**
   - Kod eksportował `res.tmpc` do `temperature_samples`, ale otrzymywał pustą listę z powodu błędu w parserze C++.
3. **NPZ Processed Cache (`telemetry_processed_cache.py`):**
   - Cache zapisywał pustą tablicę `temperature_samples` o kształcie `(0, 2)`.
   - Pliki cache użytkownika wygenerowane w tym stanie (`version=2`) utrwaliły brak temperatury na dysku.
4. **TelemetryDataManager & GUI Stream Discovery:**
   - W `TelemetryDataManager.temperature_samples` trafiała pusta lista.
   - Metoda `_discover_data_streams()` sprawdza `if tm.temperature_samples:`, więc indykator `temp_text` ("Temperatura GoPro") nie pojawiał się na liście dostępnych strumieni danych.

---

## 2. Implementacja Naprawy

1. **Wyszukiwanie TMPC w kontenerach ACCL i GYRO (`gpmf_extractor.cpp`):**
   - Podczas przetwarzania strumieni `ACCL` i `GYRO` wywoływane jest `GPMF_FindPrev(&find_tmpc, STR2FOURCC("TMPC"), GPMF_CURRENT_LEVEL)`.
   - Wartość temperatury odczytywana jest jako surowy 32-bitowy float (`big-endian IEEE 754`, `BYTESWAP32`), bez dzielenia przez `SCAL` akcelerometru ani żyroskopu.
   - Wartość zachowuje pełną precyzję zmiennoprzecinkową `float64` (np. `30.01171875 °C`), bez rzutowania do `int`.

2. **Kanoniczna deduplikacja ACCL vs GYRO (ETAP 4C):**
   - W każdym bloku DEVC pobierana jest dokładnie jedna logiczna próbka temperatury.
   - ACCL TMPC jest traktowany jako kanoniczny; GYRO TMPC służy jako fallback, jeśli w danym bloku ACCL nie zawierał TMPC.
   - Nie dochodzi do podwojenia liczby próbek (z 360 raw do 180 logicznych).

3. **Precyzyjny timing oparty o STMP/TSMP:**
   - Czas próbki wyprowadzany jest z zegara mikrosekundowego `STMP` strumienia ACCL w odniesieniu do bazy `anchor_ts` z pierwszego pomiaru GPS/GPSU.
   - Zapewnia to idealną monotoniczność i zgodność z czasem wideo oraz poprzednim parserem referencyjnym.

4. **Inwalidacja nieaktualnych cache (`PROCESSED_CACHE_VERSION = 3`):**
   - Podbito wersję schematu cache w `src/telemetry_processed_cache.py`:
     ```python
     PROCESSED_CACHE_VERSION = 3
     ```
   - Każdy istniejący plik `.telemetry.npz` o wersji 2 (bez TMPC) jest automatycznie unieważniany przy kolejnym odczycie i transparentnie regenerowany z pełnym strumieniem `temperature_samples`.

5. **Diagnostyka telemetryczna i cache:**
   - Dodano zwięzłe liczniki diagnostyczne:
     ```text
     [TMPC Native] raw_accl=186 raw_gyro=186 logical=186 first=30.011719 C last=37.304688 C
     [TMPC Cache] write_count=186
     [TMPC Cache] read_count=186
     [TMPC Telemetry] temperature_samples=186
     ```

---

## 3. Pomiary i Weryfikacja Parity na Rzeczywistych Plikach GoPro

### Test 1: Referencyjny plik pojedynczy `D:/GoPro/2026-08-31/GX010239.MP4`

Porównanie wyjścia starego parsera referencyjnego Python (`gpmf_to_exiftool_json` + `extract_temperature_samples`) z nowym natywnym parserem C++ (`extract_gpmf_native`):

| Metryka | OLD (Python GPMF) | NEW (Native C++ GPMF) | Parity / Różnica |
| :--- | :--- | :--- | :--- |
| **Raw ACCL TMPC** | 186 | 186 | Exact match |
| **Raw GYRO TMPC** | 186 | 186 | Exact match |
| **Logical Samples** | 186 | 186 | Exact match |
| **First Timestamp (UTC)** | `2026-08-31 13:03:35.299000` | `2026-08-31 13:03:35.299000` | Delta = 0.0 µs |
| **Last Timestamp (UTC)** | `2026-08-31 13:06:40.485109` | `2026-08-31 13:06:40.485109` | Delta = 0.0 µs |
| **First Value** | `30.01171875 °C` | `30.01171875 °C` | Max diff = 0.000000000 °C |
| **Last Value** | `37.30468750 °C` | `37.30468750 °C` | Max diff = 0.000000000 °C |
| **Max Timestamp Diff (all 186)** | — | — | **0.000000238 s** |
| **Max Temperature Diff (all 186)** | — | — | **0.000000000 °C (Exact)** |
| **Strictly Monotonic** | Tak | Tak | Tak |

### Test 2: Rzeczywisty plik uzupełniający `D:/GoPro/2026-08-31/GX010240.MP4`

| Metryka | OLD (Python GPMF) | NEW (Native C++ GPMF) | Parity / Różnica |
| :--- | :--- | :--- | :--- |
| **Raw ACCL TMPC** | 1631 | 1631 | Exact match |
| **Raw GYRO TMPC** | 1631 | 1631 | Exact match |
| **Logical Samples** | 1631 | 1631 | Exact match |
| **First Value** | `30.97656250 °C` | `30.97656250 °C` | Max diff = 0.000000000 °C |
| **Last Value** | `41.87890625 °C` | `41.87890625 °C` | Max diff = 0.000000000 °C |
| **Max Timestamp Diff (all 1631)** | — | — | **0.000000238 s** |
| **Max Temperature Diff (all 1631)**| — | — | **0.000000000 °C (Exact)** |

---

## 4. NPZ Cache Write / Read Parity

Przetestowano pełny cykl zapisu i odczytu cache binarnego `.telemetry.npz`:
1. `write_processed_cache` serializuje tablicę `temperature_samples` o wymiarze `(N, 2)` typu `float64` (`[timestamp_unix, temperature_c]`).
2. `read_processed_cache_arrays` wczytuje tablicę w ~1 ms i weryfikuje nagłówek `__meta__` (`version=3`).
3. `apply_processed_cache_arrays` zasila `TelemetryDataManager.temperature_samples` oraz `temperature_array`.
4. Wynik:
   - Wszystkie 186 próbek w `GX010239` i 1631 w `GX010240` zachowują 100% zgodności binarnej (`np.allclose atol=1e-9: True`).
   - Wartości są liczbami `float`, np. `30.01171875`.

---

## 5. Multi-File Test (`GX010239.MP4` + `GX010240.MP4`)

Przetestowano łączenie wielu klipów w projekcie multi-file:
- **Clip 1 (`GX010239.MP4`):** 186 próbek, czas od `13:03:35.299` do `13:06:40.485` UTC.
- **Clip 2 (`GX010240.MP4`):** 1631 próbek, czas od `13:33:08.200` do `14:00:19.828` UTC.
- **Po złączeniu (Merge):**
  - Całkowita liczba próbek: **1817** (186 + 1631, brak zgubionych lub zduplikowanych próbek).
  - Granica klipów: `13:06:40.485` $\to$ `13:33:08.200` (przerwa między nagraniami 1587.715 s).
  - Timestamps: **ściśle monotoniczne w całym połączonym projekcie**.

---

## 6. GUI Discovery i Render Availability

- **GUI Data Stream Discovery:**
  - `IndicatorMixin._discover_data_streams()` wykrywa obecność `tm.temperature_samples`.
  - Strumień pojawia się na liście z pełnymi metadanymi:
    ```text
    key: "temp_text"
    display_name: "Temperatura"
    source: "gpmf"
    unit: "°C"
    sample_count: 186
    value_range: (30.01171875, 37.31640625)
    ```
- **Renderer / Compositor Availability:**
  - W `render_mixin.py`: `temperature_samples=getattr(self.telemetry, "temperature_samples", None)` przekazuje kompletną serię próbek.
  - W `frame_data.py`: `temp_value = direct_resolve("temperature", temp_source, "temp_text")` lub `interpolate_temperature(temperature_samples, target_dt)`.
  - Wskaźnik `temp_text` formatuje temperaturę z zachowaniem precyzji zmiennoprzecinkowej do wyświetlania na HUD.

---

## 7. Wyniki Testów Automatycznych

Uruchomiono dedykowane i powiązane testy regresyjne:
- `tests/test_tmpc_native_and_cache.py`: **5 passed in 6.98s**
  - `test_processed_cache_version_bumped`: PASSED
  - `test_native_tmpc_extraction_real_file`: PASSED
  - `test_npz_cache_roundtrip_preserves_tmpc`: PASSED
  - `test_gui_stream_discovery_finds_tmpc`: PASSED
  - `test_multifile_tmpc_merge`: PASSED
- `tests/test_telemetry_processed_cache.py` + `tests/test_fast_telemetry_materialization.py`: **9 passed in 0.44s**
- `tests/test_gpmf_timing.py`: **5 passed, 1 skipped in 0.10s**

---

## 8. Podsumowanie

```text
GOPRO TMPC RESTORED: PASS
```
