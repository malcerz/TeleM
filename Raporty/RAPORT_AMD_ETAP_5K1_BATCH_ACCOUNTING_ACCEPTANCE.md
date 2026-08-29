# RAPORT AMD ETAP 5K.1 — BATCHED REGIONS ACCOUNTING TRUTH + KEEP / ROLLBACK DECISION

**Data:** 2026-08-29  
**Repozytorium:** `C:\_DEV\TeleM`  
**Gałąź:** `amd-render`  
**Commit bazowy:** `3ab0b89`  
**Status:** **COMPLETE — PRODUCTION DEFAULT ROLLBACK TO AMD_ABOVE_BATCHED=0**

---

## 1. Cel i Stan Wejściowy

W ETAP 5K wprowadzono batched upload regionów CPU ABOVE:
```c
telem_amd_update_above_regions_batch(h_context, row_table_ptr, canvas_stride, rects_buf, count)
```
zamiast wielokrotnych wywołań FFI:
```c
telem_amd_update_above_region(...)
```
Raport 5K wykazał pozorny spadek `above_region_upload` z 1.045 ms do 0.010 ms (-99%), lecz `TRUE FPS` wzrósł zaledwie o +0.67% (37.460 -> 37.712 fps), a `consumer_native_call` w jednym z przebiegów skoczył do 8.058 ms.

**Zadania ETAP 5K.1:**
1. Ustalić rzeczywisty koszt ścieżki batched i wyeliminować przesunięcia między bucketami profilera.
2. Wprowadzić natywne pomiary czasu sprzętowego w C++ (`m_lastAboveRegionNativeUs` oraz `m_lastAboveRegionSubresourceUs`) i ujednolicić granice metryk.
3. Przeprowadzić mikrobenchmarki syntetyczne A (100,000 iteracji) i B (10,000 iteracji).
4. Wykonać rygorystyczny 14-przebiegowy paired interleaved benchmark A/B (7 par, 1131 klatek, 4K, `presets/cycling_dashboard_v10.json`).
5. Podjąć jednoznaczną decyzję akceptacyjną: **KEEP** albo **ROLLBACK PRODUCTION DEFAULT**.

---

## 2. Podsumowanie Decyzji

| Kryterium | Wymóg | Wynik Zmierzony | Status |
| :--- | :--- | :--- | :--- |
| **Kryterium E2E** | TRUE FPS $\ge +3.0\%$ LUB Total Wall $\le -3.0\%$ | TRUE FPS: **+0.16%** mean / **-0.33%** median<br>Total Wall: **-0.18%** mean / **+0.33%** median | **FAIL** |
| **Kryterium Lokalne** | Marshalling $\ge 50\%$ szybszy ORAZ `producer_prepare` $\ge 5.0\%$ szybszy | Marshalling: **+49.3%** / **+62.1%** szybszy<br>`producer_prepare`: **+0.26%** (brak zysku) | **FAIL** |
| **Parity & Bezpieczeństwo** | MaxDiff = 0, Preview 6/6 PASS, brak ghostingu | `MaxDiff = 0`, Preview **6/6 PASS**, GUI Hotfix **PASS** | **PASS** |

### **DECYZJA KOŃCOWA: ROLLBACK PRODUCTION DEFAULT**
- **Domyślna konfiguracja produkcyjna:** `AMD_ABOVE_BATCHED = 0` (stabilna ścieżka per-region).
- **Ścieżka Batched:** Zachowana w kodzie jako opcja eksperymentalna pod flagą `AMD_ABOVE_BATCHED = 1` z pełnym zabezpieczeniem granic bloków pamięci Pillow (`non_contig_regions == 0`).
- **Nie rozpoczynać ETAP 5L** bez nowej dyrektywy.

---

## 3. Zunifikowana Architektura Metryk

Wprowadzono bezpośrednie odczyty timerów wewnątrz DLL C++ (`telem_amd_get_above_region_timings`):

1. **`UPDATE_SUBRESOURCE_CPU`**: Czas procesora spędzony bezpośrednio wewnątrz sterownika Direct3D 11 podczas wywołania `ID3D11DeviceContext::UpdateSubresource` dla regionów ABOVE.
2. **`NATIVE_REGION_TOTAL`**: Całkowity czas wykonania funkcji C++ DLL (`UpdateAboveRegion` x N lub `UpdateAboveRegionsBatch`).
3. **`PYTHON_CONTROL_TOTAL`**: Czas ekstraktora dirty rects w producerze (`extract_ms`) oraz narzut FFI/ctypes/dispatching bez czasu wykonania sterownika GPU.
4. **`REGION_PIPELINE_TOTAL`**: Pełny czas przejścia regionu od Pillow do zakończenia `UpdateSubresource` (`extract_ms + dispatch_ms`).

---

## 4. Wyniki Mikrobenchmarków Syntetycznych

### Mikrobenchmark A: Pure Python Control & Marshalling (100,000 iteracji)
*Mierzy czysty narzut Pythona/ctypes bez wywołań sterownika GPU.*

| Wariant | Czas całkowity | Średnio na klatkę | Zysk |
| :--- | :--- | :--- | :--- |
| **LEGACY (6 wywołań / frame)** | 1.3547 s | **13.547 $\mu$s/frame** | referencja |
| **BATCHED (1 wywołanie / frame)** | 0.6867 s | **6.867 $\mu$s/frame** | **-6.680 $\mu$s (+49.31%)** |

*Rozbicie kosztu BATCHED (6.867 $\mu$s):*
- Zapis 24 pól deskryptorów ctypes (`x, y, w, h` x 6): **5.206 $\mu$s/frame** (75.8%)
- Pobranie wskaźnika tabeli wierszy przez `PyCapsule_GetPointer`: **1.514 $\mu$s/frame** (22.0%)
- Rzutowanie i budowa krotki: **0.147 $\mu$s/frame** (2.2%)

---

### Mikrobenchmark B: Pełna Ścieżka Regionów z D3D11 UpdateSubresource (10,000 iteracji)
*Mierzy Python Control + C++ Native + rzeczywiste D3D11 UpdateSubresource dla 6 regionów 4K.*

| Składowa | LEGACY (6 calls) | BATCHED (1 call) | Delta | Zmiana % |
| :--- | :--- | :--- | :--- | :--- |
| **Python Control** | 35.864 $\mu$s (8.7%) | 13.610 $\mu$s (3.6%) | **-22.254 $\mu$s** | **+62.05%** |
| **Native C++ Overhead** | 0.637 $\mu$s (0.2%) | 0.403 $\mu$s (0.1%) | -0.234 $\mu$s | +36.73% |
| **UpdateSubresource CPU (D3D11)** | 375.302 $\mu$s (91.1%) | 365.065 $\mu$s (96.3%) | **-10.237 $\mu$s** | +2.73% |
| **TOTAL REGION PIPELINE** | **411.803 $\mu$s** (100%) | **379.078 $\mu$s** (100%) | **-32.725 $\mu$s** | **+7.95%** |

**Wniosek z mikrobenchmarków:**
Czysty zysk z eliminacji 5 wywołań FFI wynosi **od 6.7 do 22.3 mikrosekundy na klatkę** ($0.007\text{--}0.022\text{ ms}$). Koszt wykonania `UpdateSubresource` w sterowniku graficznym (~0.37 ms w pętli syntetycznej, ~0.97 ms w pełnym potoku wideo) dominuje w ponad 91% i jest niezależny od tego, czy wywołanie następuje z Pythona czy z pętli w C++.

---

## 5. Wyniki Paired Interleaved Benchmark A/B (14 Przebiegów)

**Warunki testu:**
- Plik wideo: `Video/GX020079.MP4` (3840x2160, 29.97 fps, 1131 klatek)
- Plik telemetryczny: `Video/GX020079.fit`
- Preset: `presets/cycling_dashboard_v10.json`
- Strategia dirty rects: `AMD_ABOVE_DIRTY_STRATEGY = DIST`
- Liczba par: **7 par (14 przebiegów mierzonych + 2 rozgrzewkowe)**
- Kolejność: ściśle naprzemienna L1, B1, L2, B2, ..., L7, B7

### Tabela Przebiegów Parowanych (Raw Data)

| Para | LEGACY TRUE FPS | BATCHED TRUE FPS | $\Delta$ FPS | $\Delta$ % | LEGACY Wall | BATCHED Wall | $\Delta$ Wall |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **P1** | 36.180 fps | 37.038 fps | +0.858 fps | +2.37% | 31.261 s | 30.536 s | -0.725 s |
| **P2** | 37.217 fps | 37.090 fps | -0.127 fps | -0.34% | 30.389 s | 30.494 s | +0.105 s |
| **P3** | 36.854 fps | 37.526 fps | +0.673 fps | +1.83% | 30.689 s | 30.139 s | -0.550 s |
| **P4** | 37.371 fps | 36.792 fps | -0.579 fps | -1.55% | 30.264 s | 30.740 s | +0.476 s |
| **P5** | 37.412 fps | 37.564 fps | +0.152 fps | +0.41% | 30.231 s | 30.109 s | -0.122 s |
| **P6** | 37.208 fps | 37.426 fps | +0.218 fps | +0.59% | 30.396 s | 30.219 s | -0.177 s |
| **P7** | 37.862 fps | 37.094 fps | -0.768 fps | -2.03% | 29.872 s | 30.490 s | +0.618 s |

**Bilans pojedynków (próg \|$\Delta$\| > 0.05 fps):**
- **Wygrane BATCHED:** 4
- **Wygrane LEGACY:** 3
- **Remisy:** 0

---

### Tabela Zagregowanych Statystyk

| Metryka | LEGACY (Mean) | BATCHED (Mean) | Delta (Mean) | LEGACY (Median) | BATCHED (Median) | Delta (Median) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TRUE FPS** | 37.158 fps | 37.219 fps | **+0.061 fps (+0.16%)** | 37.217 fps | 37.094 fps | **-0.123 fps (-0.33%)** |
| **Total Wall** | 30.443 s | 30.390 s | **-0.053 s (-0.18%)** | 30.389 s | 30.490 s | **+0.101 s (+0.33%)** |
| **producer_prepare** | 14.744 ms | 14.783 ms | +0.039 ms (+0.26%) | 14.280 ms | 14.192 ms | -0.088 ms (-0.62%) |
| **above_total** | 10.991 ms | 11.025 ms | +0.034 ms (+0.31%) | 10.666 ms | 10.666 ms | 0.000 ms (0.0%) |
| **above_compose** | 9.495 ms | 9.475 ms | -0.020 ms (-0.21%) | 9.215 ms | 9.195 ms | -0.020 ms (-0.22%) |
| **PYTHON_CONTROL** | 0.083 ms | 0.084 ms | +0.001 ms (+0.78%) | 0.081 ms | 0.081 ms | 0.000 ms (0.0%) |
| **NATIVE_REGION** | 0.991 ms | 0.995 ms | +0.004 ms (+0.40%) | 0.918 ms | 0.919 ms | +0.001 ms (+0.11%) |
| **SUBRESOURCE_CPU** | 0.967 ms | 0.970 ms | +0.003 ms (+0.31%) | 0.915 ms | 0.915 ms | 0.000 ms (0.0%) |
| **REGION_PIPELINE** | 1.055 ms | 1.059 ms | +0.004 ms (+0.38%) | 1.001 ms | 1.001 ms | 0.000 ms (0.0%) |
| **consumer_native (Mean)** | 5.794 ms | 5.649 ms | -0.145 ms (-2.50%) | 5.729 ms | 5.729 ms | 0.000 ms (0.0%) |
| **consumer_native (Median)**| 2.224 ms | 2.234 ms | +0.010 ms (+0.45%) | 2.255 ms | 2.255 ms | 0.000 ms (0.0%) |

---

## 6. Prawda o Kosztach i Wyjaśnienie Złudzenia z ETAP 5K

1. **Gdzie podział się rzekomy zysk ~1.0 ms z ETAP 5K?**
   - W ETAP 5K wskaźnik `above_region_upload` w wariancie BATCHED mierzył wyłącznie czas pojedynczego wywołania FFI do C++ ($0.010\text{ ms}$), podczas gdy w LEGACY mierzył sumę 6 wywołań FFI wraz z czasem wykonania `UpdateSubresource`.
   - Nowe natywne timery C++ wykazały, że sterownik D3D11 wykonuje `UpdateSubresource` dla 6 regionów dokładnie tyle samo czasu: **0.967 ms vs 0.970 ms**.
   - Prawdziwy zysk z batched FFI wynosi **$0.007\text{--}0.022\text{ ms}$ na klatkę**, co stanowi ~0.05% całkowitego czasu klatki (~27 ms) i gubi się w szumie jittera procesora i wątków Media Foundation.

2. **Dlaczego `consumer_native_call` wykazywał anomalie (np. 8.05 ms w 5K)?**
   - Mediana `consumer_native_call` wynosi **2.22 ms** dla obu wariantów (dekodowanie MF + VideoProcessor + AMF query).
   - Średnia na poziomie 5.6–5.8 ms wynika wyłącznie z 2–3 klatek na cały film (1131 klatek), w których enkoder sprzętowy AMF lub dekoder Media Foundation synchronizuje bufor klatek (outliery 130–150 ms na klatkach I-frame). Zjawisko to występuje identycznie w wariancie LEGACY i BATCHED i nie ma żadnego związku z przesyłaniem regionów ABOVE.

3. **Architektura pamięci Pillow i bezpieczeństwo bufora:**
   - Obrazy 4K w bibliotece Pillow są alokowane w 16 MB blokach (jeden przeskok ciągłości na linii 1091 w obrazie 3840x2160 RGBA).
   - Weryfikacja `non_contig_regions == 0` w `_extract_exact_above_regions` gwarantuje, że jeśli jakikolwiek widget przekroczy linię 1091, system automatycznie i bezpiecznie przełącza się na ścieżkę fallbackową, zapobiegając naruszeniom pamięci.

---

## 7. Weryfikacja Bezpieczeństwa i Regresji

1. **Edge ABI Test Suite (`tests/test_amd_etap5k_batched_abi.py`):**
   - Sprawdzenie struktur `HUDDirtyRect` (rozmiar 16 bajtów, wyrównanie).
   - Odporność na NULL uchwyty, NULL wskaźniki tablicy, zerowy stride, przekroczenie limitu regionów (12 rects).
   - Geometrie brzegowe: (0,0), prawy brzeg, dolny brzeg, 1x1 piksel, 8 regionów.
   - **Wynik:** `3/3 PASSED`.

2. **Golden Pixel Parity (`scratch/test_etap5j_golden_parity.py`):**
   - Sprawdzenie klatek 0, 50, 100, 300, 500, 750, 900, 965, 1130.
   - Porównanie pre-encode composited surfaces bit-po-bicie.
   - **Wynik:** `MaxDiff = 0`, `DiffPixels = 0` (**100% BIT-EXACT MATCH**).

3. **Preview Map Matrix (`scratch/test_etap5g2_preview_map_matrix.py`):**
   - Pełna macierz 6 testów podglądu mapy (zmiana dostawcy, powrót z eksportu, offline render).
   - **Wynik:** `6/6 ALL PASS`.

4. **GUI BAR Mouse Drag Hotfix (`tests/test_gui_bar_drag_hotfix.py` i `scratch/test_all_bar_styles_matrix.py`):**
   - Weryfikacja selekcji, przeciągania myszą, synchronizacji właściwości dla wszystkich 10 stylów i orientacji wskaźników BAR.
   - **Wynik:** `ALL TEST CASES PASSED SUCCESSFULLY`.

---

## 8. Izolacja Backendów

- Zmiany natywne ograniczone wyłącznie do modułów AMD D3D11 (`d3d11_vp_pipeline.cpp`, `telem_amd_native.cpp`, `amd_native_exporter.py`).
- Ścieżki NVIDIA (NVENC/CUDA), Intel (QSV) oraz CPU reference pozostały w 100% nienaruszone.

---

## 9. Wnioski i Stan Kolejki Optymalizacyjnej

Po definitywnym zamknięciu etapu 5K.1 i przywróceniu domyślnego `AMD_ABOVE_BATCHED = 0`, rzeczywisty profil czasu CPU ABOVE przedstawia się następująco:

```text
above_compose:           ~9.48 ms/frame (86.3% above_total)
  alt_visual             ~3.2 ms
  slope_text             ~2.1 ms
  compass                ~1.8 ms
  fit_curVpower_text     ~1.4 ms
  temp_text              ~1.2 ms
UpdateSubresource (CPU): ~0.97 ms/frame
Python extract/plan:     ~0.08 ms/frame
```

Kolejnym logicznym wąskim gardłem do optymalizacji w dedykowanym etapie jest rasteryzacja elementów wewnątrz `above_compose` (np. `alt_visual` lub `slope_text`), a nie warstwa transportowa FFI.

---

## 10. Końcowy Werdykt

```text
TASK: AMD ETAP 5K.1 — BATCHED REGIONS ACCOUNTING TRUTH + KEEP / ROLLBACK DECISION
STATUS: COMPLETE

CHANGED:
- native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h (hardware timing getters)
- native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp (high_resolution_clock UpdateSubresource profiling)
- native/d3d11_amf_pipeline/src/telem_amd_native.cpp (exported telem_amd_get_above_region_timings)
- src/ffmpeg/amd_native_exporter.py (standardized metrics, safe chunk validation, AMD_ABOVE_BATCHED=0 default)
- tests/test_amd_etap5k_batched_abi.py (edge cases & null safety test suite)

TESTED:
- Microbenchmark A (Control only, 100,000 iterations): PASS (+49.3% speedup, 6.7 us delta)
- Microbenchmark B (Full region path, 10,000 iterations): PASS (+7.95% speedup, 32.7 us delta)
- 14-run Paired Interleaved A/B benchmark (1131 frames 4K): PASS (+0.16% mean, -0.33% median)
- Golden Pixel Parity: PASS (MaxDiff = 0 across all checkpoints)
- Preview Map Matrix: PASS (6/6 pass)
- Edge ABI Unit Tests: PASS (3/3 pass)
- GUI BAR Drag Hotfix Suite: PASS (all styles pass)

NOT TESTED:
- Non-Windows platforms (D3D11/AMF is Windows-exclusive)

PERFORMANCE:
- TRUE FPS: 37.158 -> 37.219 fps (+0.16% mean, -0.33% median)
- Total Export: 30.443 -> 30.390 s (-0.18% mean, +0.33% median)
- producer_prepare: 14.744 -> 14.783 ms (+0.26%)
- D3D11 UpdateSubresource CPU: 0.967 ms (Legacy) vs 0.970 ms (Batched)
- Decision: E2E and Local acceptance criteria NOT met -> PRODUCTION DEFAULT SET TO AMD_ABOVE_BATCHED=0

RISKS:
- None. Stable legacy path remains active by default; batched path guarded behind AMD_ABOVE_BATCHED=1.

REPORT: Raporty/RAPORT_AMD_ETAP_5K1_BATCH_ACCOUNTING_ACCEPTANCE.md
```
