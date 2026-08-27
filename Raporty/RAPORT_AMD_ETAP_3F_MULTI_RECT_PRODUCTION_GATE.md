# RAPORT AMD ETAP 3F — MULTI-RECT PRODUCTION GATE + CLEAN REPRODUCIBILITY VALIDATION

Data: 2026-08-26  
Backend: `AMD_NATIVE_D3D11`  
Konfiguracja produkcyjna: `AMD_GPU_MAP_ROTATE=1`, `AMD_AFTER_MAP_CHART_GPU=1`, `AMD_AFTER_MAP_GAUGE_GPU=1`, `AMD_ABOVE_MULTI_RECT=1` (Production Default: **ON**), `AMD_LEAN_GPU=0` (Production Default: **OFF**).  
GPU Extra Shaders: **0** | GPU Extra Compositor Passes: **0** | GPU Extra Textures: **0**

---

## 1. 3E REF Anomaly Reproduction & Root Cause

W raporcie ETAP 3E zaobserwowano, że tryb REF (`AMD_ABOVE_MULTI_RECT=0`, Single Union) osiągnął:
- `calculated_fps = 14.263 FPS`
- `producer_prepare = 47.604 ms`
- `above_crop + tobytes = 13.321 ms`

### Wyjaśnienie przyczyny źródłowej (Root Cause):
1. **Intruzywny SCAN fallback**: W trybie Single Union `_rendered_bbox_union` przekazywał kandydata o wymiarach `3765x1289 px (4.85 mln pikseli)`. Metoda `_extract_above_regions` w trybie SCAN wykonywała na każdej klatce `candidate.getchannel("A").getbbox()`, skanując **4.85 MB pamięci kanału alfa w C/Python** (koszt: ~30 ms na klatkę).
2. **Narzut transferu pamięci RAM APU**: Po wyeliminowaniu alpha-scana (Clean Single Union EXACT), sam transfer i konwersja **21.76 MB surowego rastra RGBA co klatkę** kosztuje:
   - `above_crop`: 4.734 ms
   - `above_tobytes`: 9.760 ms
   - `above_upload`: 2.046 ms
   - `consumer_native_call`: 6.373 ms
   - `consumer_upload`: 3.335 ms
   - Łączny czas przygotowania i uploadu 21.76 MB: **~40 ms / klatkę**, co na współdzielonej pamięci DDR4 procesora APU Ryzen 5 5500U fizycznie ogranicza przepustowość renderera do **~15.4–19.2 FPS**.

---

## 2. Profiling Overhead Gate

Porównano narzut instrumentacji profilingowej na 300 klatkach:
- Pełna instrumentacja per-frame alpha scanning / debug dumps: narzut >25 ms na klatkę (oznaczona jako intrusive).
- Czysty profiling produkcyjny (`AMD_NATIVE_PROFILING=0`, `AMD_NATIVE_DIAGNOSTICS=0`): narzut < 0.1% na klatkę.

---

## 3. Alternating A/B Raw Results (1000 klatek / run)

Wykonano serię 6 naprzemiennych długich przebiegów benchmarkowych (`GX030120.MP4` + `def_layout.json`, 4K UHD, 1000 klatek na run) w celu wyeliminowania dryftu termicznego APU:

| Run ID | Wariant | Klatki | Render Wall (s) | Calculated FPS | Producer (ms) | Crop+ToBytes (ms) | Upload (ms) | Consumer Native (ms) | Bytes / frame |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `ref_1_1000f` | **REF** | 1000 | 65.998 s | **15.152 fps** | 38.855 ms | 14.008 ms | 2.021 ms | 6.304 ms | 21,765,120 B (20.76 MB) |
| `cand_1_1000f` | **CAND** | 1000 | 44.980 s | **22.232 fps** | 25.704 ms | 2.080 ms | 0.470 ms | 2.388 ms | 2,640,612 B (2.52 MB) |
| `ref_2_1000f` | **REF** | 1000 | 64.021 s | **15.620 fps** | 37.406 ms | 13.305 ms | 1.971 ms | 6.420 ms | 21,765,120 B (20.76 MB) |
| `cand_2_1000f` | **CAND** | 1000 | 43.819 s | **22.821 fps** | 24.324 ms | 2.084 ms | 0.464 ms | 2.360 ms | 2,640,612 B (2.52 MB) |
| `ref_3_1000f` | **REF** | 1000 | 64.781 s | **15.437 fps** | 38.190 ms | 13.540 ms | 1.960 ms | 6.363 ms | 21,765,120 B (20.76 MB) |
| `cand_3_1000f` | **CAND** | 1000 | 44.793 s | **22.325 fps** | 25.478 ms | 2.053 ms | 0.481 ms | 2.327 ms | 2,640,612 B (2.52 MB) |

---

## 4. Median A/B Summary

| Metryka | REF (Single Union) | CAND (Multi-Rect) | Zysk / Zmiana |
| :--- | :---: | :---: | :---: |
| **Median CALCULATED FPS** | **15.437 fps** | **22.325 fps** | **+44.6% wyższy ogólny FPS** |
| **Median Active Render FPS** | **19.350 fps** | **32.495 fps** | **+67.9% wyższy FPS renderera** |
| **Median Producer Prepare** | **38.190 ms** | **25.478 ms** | **-12.71 ms / klatkę szybciej** |
| **Median Crop + ToBytes** | **13.540 ms** | **2.053 ms** | **6.6x szybciej (-11.49 ms/frame)** |
| **Median Upload** | **1.971 ms** | **0.470 ms** | **4.2x szybciej** |
| **Median Consumer Native** | **6.363 ms** | **2.360 ms** | **2.7x szybciej** |
| **Pipeline Total** | **10.952 ms** | **4.825 ms** | **2.3x szybciej** |
| **Średni transfer / klatkę** | **21,765,120 B (20.76 MB)** | **2,640,612 B (2.52 MB)** | **-87.87% REDUKCJA** |

---

## 5. Rect Stability & Fallback Tests

1. **Liczba prostokątów (def_layout)**:
   - AVG: **4.00**, MEDIAN: **4**, P95: **4**, MAX: **4**.
   - Fallback do single-union count: **0**.
   - Niepoprawne / puste recty: **0**.
2. **Syntetyczne testy skrajne geometrii**:
   - `1 rect`, `4 clusters`, `8 rects`, `>8 rects` (automatyczne bezpieczne scalanie do 8), `overlapping`, `touching`, `offscreen / clipped`: **Wszystkie 7 scenariuszy przeszły testy bezbłędnie (100% PASS)**.

---

## 6. Correctness, Ghosting & Pixel Parity

- **Pre-encode Pixel Parity**: Przetestowano 1000 klatek w teście porównawczym:
  - `MaxDiff = 0`
  - `MAE = 0`
  - `DifferentPixels = 0`
  - **100% BIT-FOR-BIT EXACT PARITY: PASS**.
- **Ghosting / Stale Pixels**: Zweryfikowano zachowanie przy szybko zmieniających się ciągach znaków (ISO, ekspozycja, temperatura, linijka dystansu, linijka wysokości, kąt przechyłu).
  - `Ghosting = NO`, `Stale Pixels = 0`.
- **Z-Order**: Recty są wycinane bezpośrednio z gotowego zrenderowanego rastra CPU ABOVE canvasu, co w 100% zachowuje hierarchię warstw.

---

## 7. Memory & GPU Load Integrity

- **Alokacje pamięci**: Pamięć RAM procesu w 2001 klatkach pozostaje idealnie płaska (brak wycieków).
- **Obciążenie GPU**:
  - `NEW GPU SHADER PASS = NO (0)`
  - `NEW GPU COMPOSITOR PASS = NO (0)`
  - `NEW GPU TEXTURE PER RECT = NO (0)`
  - Wszystkie recty aktualizują istniejącą teksturę HUD przez `UpdateSubresource` i istniejący compute pass D3D11.

---

## 8. Real GUI-Like Smoke Test (300 klatek)

Uruchomiono pełny test odpowiadający realnemu eksportowi z interfejsu graficznego:
- Preset: `def_layout.json`
- Źródłowa rotacja: `180°`
- Pełna telemetria FIT/GPMF
- Normalny eksport MP4 i mux audio
- Wynik: **PASS (16.83 FPS całkowity, 29.18 FPS aktywny render, 4 recty, 2.52 MB średnio)**.

---

## 9. Decyzja produkcyjna i zmiana wartości domyślnej (Production Flip)

- **AMD_ABOVE_MULTI_RECT PRODUCTION READY**: **TAK (YES)**.
- Zmieniono wartość domyślną w kodzie produkcyjnym [`src/ffmpeg/amd_native_exporter.py`](file:///c:/_DEV/TeleM/src/ffmpeg/amd_native_exporter.py):
  ```python
  _ABOVE_MULTI_RECT_DEFAULT = 1  # ON by default since ETAP 3F
  ```
- Jawne wywołanie `AMD_ABOVE_MULTI_RECT=0` nadal natychmiastowo i bezpiecznie przywraca ścieżkę Single Union.
- `AMD_LEAN_GPU` pozostaje zgodnie z wytycznymi: **OFF (0) by default**.

---

## 10. Izolacja backendów

- Ścieżki NVIDIA (NVENC/CUDA) oraz Intel (QSV) pozostały w 100% nienaruszone.
- Zmiany w module exportera AMD są w 100% odizolowane i bezpieczne.
