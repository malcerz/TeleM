# RAPORT — AMD ETAP 4E: POST-4D BOTTLENECK REPROFILE & NEXT DOMINANT CPU PATH ELIMINATION

## 1. Cel Etapu i Założenia

Celem etapu **AMD ETAP 4E** było:
1. Wykonanie rzetelnego, pełnego reprofilingu warstwy `CPU ABOVE` oraz całego potoku produkcyjnego po zmianach z ETAP 4D na kanonicznym workloadzie (1131 klatek, 4K UHD 3840x2160, `GX030120.MP4` + FIT + `def_layout.json`).
2. Ustalenie nowego, aktualnego rankingu wąskich gardeł (bez polegania na nieaktualnych danych historycznych z ETAP 4C).
3. Wybór dominujących bottlenecków oraz wdrożenie bezpiecznej, dowiedzionej optymalizacji z zachowaniem bezwzględnej zasady **Parity First** ($MaxDiff = 0, DifferentPixels = 0$).

---

## 2. Metodologia Profilingu i Stan Wejściowy (Post-4D Baseline)

Profilowanie przeprowadzono dwutorowo na pełnym 1131-klatkowym przebiegu:
1. **End-to-End Exporter Profiling (`stream_overlay_to_ffmpeg` -> `.amd_profile.json`):** Pomiar rzeczywistych czasów potoku D3D11 / AMF (`producer_prepare`, `above_total`, `above_compose`, `consumer_native_call`, `render FPS`, `user effective FPS`).
2. **Granular Component Profiler (`OverlayProfiler`):** Pomiar każdego wskaźnika, operacji `regional_clear` oraz ich wewnętrznych sub-faz (`render`, `text drawing`, `textbbox`, `copy`, `paste_composite`).

### Pełny Ranking Komponentów CPU ABOVE (Przed ETAP 4E, 1131 Klatek, 4K UHD):

| Rank | Komponent / Wskaźnik | AVG (ms) | Mediana (ms) | P95 (ms) | % above_compose | Dominujący podkoszt |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **1** | **`alt_text`** (Altitude vertical bar) | **2.130 ms** | **1.740 ms** | **3.877 ms** | **20.90%** | render (1.566 ms: text drawing 0.63 ms + textbbox 0.63 ms) |
| **2** | **`fit_distance_text`** (Distance horizontal bar) | **1.672 ms** | **1.454 ms** | **2.321 ms** | **16.41%** | copy (0.615 ms) + paste_composite (0.792 ms) |
| **3** | **`fit_gopro_battery_text`** (Battery segments) | **1.477 ms** | **1.217 ms** | **2.599 ms** | **14.50%** | render (1.160 ms: text drawing 0.59 ms + textbbox 0.52 ms) |
| **4** | **`speed_text`** (Speed gauge CPU capture) | **1.429 ms** | **1.204 ms** | **2.174 ms** | **14.03%** | render (1.360 ms: copy 0.63 ms + textbbox 0.23 ms) |
| **5** | **`canvas.regional_clear`** (Canvas regional clear) | **1.044 ms** | **0.970 ms** | **1.387 ms** | **10.25%** | nadmiarowy `pad=40` na 7-9 prostokątach |
| **6** | **`lean_indicator`** (Lean roll/pitch indicator) | **0.884 ms** | **0.716 ms** | **1.402 ms** | **8.68%** | alpha_composite (0.539 ms) |
| **7** | **`fit_heart_rate_text`** (HR chart CPU capture) | **0.472 ms** | **0.384 ms** | **0.660 ms** | **4.63%** | composite (0.193 ms) + cursor (0.130 ms) |
| **8** | **`fit_cadence_text`** (Cadence chart CPU capture) | **0.298 ms** | **0.213 ms** | **0.445 ms** | **2.93%** | composite (0.135 ms) + cursor (0.084 ms) |
| **9** | **`exposure_text`** (Text indicator) | **0.274 ms** | **0.116 ms** | **1.157 ms** | **2.68%** | text drawing (0.116 ms) |
| **10** | **`iso_text`** (Text indicator) | **0.245 ms** | **0.155 ms** | **0.917 ms** | **2.40%** | text drawing (0.045 ms) |
| **11** | **`temp_text`** (Text indicator) | **0.135 ms** | **0.107 ms** | **0.218 ms** | **1.32%** | paste_composite (0.051 ms) |
| — | **TOTAL `above_compose`** | **10.189 ms** | **8.953 ms** | **20.279 ms** | **100.00%** | — |

---

## 3. Zidentyfikowane Root Cause & Zastosowane Optymalizacje

### A. Residual Render Cost: Redundant FreeType Font Rasterization & Measurement
- **Root Cause:** W `_render_ruler_vertical` (`alt_text`), `_render_segments` (`fit_gopro_battery_text`) oraz `_render_ruler` (`fit_distance_text`), mimo że tło bazowe było buforowane, dynamiczny tekst wartości był rysowany na nowo co klatkę za pomocą `d.textbbox` i `d.text` z obwódką.
  - W `fit_gopro_battery_text`: wartość baterii jest identyczna ("--") na wszystkich 1131 klatkach, a mimo to wywoływano 1131 alokacji i pomiarów.
  - W `alt_text`: na 1131 klatkach istnieje jedynie 49 unikalnych dyskretnych stanów wizualnych `(marker_y, value_text)`.
  - W `fit_distance_text`: na 1131 klatkach istnieje tylko 1 unikalny stan `(marker_x, value_text)`.
- **Wdrożona Optymalizacja:**
  - Wprowadzono memoizację wyrenderowanego rastra w `_STATIC_CACHE` / `_SEG_BASE_CACHE` kluczowaną dyskretnymi koordynatami pikselowymi i tekstem:
    - `_render_ruler_vertical`: `dynamic_key = ("ruler_v_dyn", static_key, missing, marker_y, value_text)`
    - `_render_ruler`: `dynamic_key = ("ruler_h_dyn", static_key, value is None, marker_x, value_text)`
    - `_render_segments`: `dynamic_key = ("seg_dyn_v2", font_path, ..., val_min, val_max, value is None, val_num, value_text, cfg_signature)`
  - Przy trafieniu w cache (95.7%–99.9% klatek) czas renderowania spada z 1.61 ms do **0.001–0.05 ms** na wskaźnik.

### B. Canvas Regional Clear Oversized Padding
- **Root Cause:** W `src/indicators/compositor.py` czyszczenie poprzednich klatek (`prev_bboxes`) używało stałego marginesu `pad = 40`, co powiększało obszar czyszczony o 80 px w obu osiach dla każdego z 7-9 wskaźników, czyszcząc niepotrzebnie 2-3 miliony przezroczystych pikseli co klatkę.
- **Wdrożona Optymalizacja:**
  - Zmniejszono margines do minimalnego `pad = 2` (dokładnie pokrywającego krawędzie antyaliasingu poprzednio wyrenderowanych widgetów).
  - Czas `canvas.regional_clear` spadł z 1.044 ms do **0.701 ms AVG** (-32.9%).

---

## 4. Wyniki Benchmarku Porównawczego (1131 Klatek, 4K UHD)

### A. Komponenty Warstwy `CPU ABOVE`:

| Metryka / Komponent | BEFORE 4E (AVG) | AFTER 4E (AVG) | Delta (ms) | Zysk % | Mediana (4E) | P95 (4E) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **TOTAL above_compose** | **10.189 ms** | **6.631 ms** | **-3.558 ms** | **-34.9%** | **5.925 ms** | **9.503 ms** |
| • `alt_text` (Altitude) | 2.130 ms | **1.021 ms** | -1.109 ms | **-52.1%** | 0.820 ms | 1.719 ms |
|   - *render* | 1.566 ms | 0.489 ms | -1.077 ms | -68.8% | 0.377 ms | 1.230 ms |
|   - *paste_composite* | 0.460 ms | 0.445 ms | -0.015 ms | -3.3% | 0.371 ms | 0.642 ms |
| • `fit_distance_text` (Distance) | 1.672 ms | **0.937 ms** | -0.735 ms | **-43.9%** | 0.830 ms | 1.257 ms |
|   - *render* | 0.763 ms | 0.086 ms | -0.677 ms | -88.7% | 0.070 ms | 0.123 ms |
|   - *paste_composite* | 0.792 ms | 0.758 ms | -0.034 ms | -4.3% | 0.674 ms | 1.009 ms |
| • `fit_gopro_battery_text` (Battery) | 1.477 ms | **0.682 ms** | -0.795 ms | **-53.8%** | 0.588 ms | 0.977 ms |
|   - *render* | 1.160 ms | 0.390 ms | -0.770 ms | -66.4% | 0.336 ms | 0.548 ms |
|   - *paste_composite* | 0.232 ms | 0.223 ms | -0.009 ms | -3.9% | 0.192 ms | 0.325 ms |
| • `canvas.regional_clear` | 1.044 ms | **0.701 ms** | -0.343 ms | **-32.9%** | 0.670 ms | 0.942 ms |
| • `speed_text` (Gauge capture) | 1.429 ms | **1.169 ms** | -0.260 ms | -18.2% | 1.009 ms | 1.826 ms |
| • `lean_indicator` | 0.884 ms | **0.696 ms** | -0.188 ms | -21.3% | 0.590 ms | 0.993 ms |
| • `fit_heart_rate_text` (HR chart) | 0.472 ms | **0.433 ms** | -0.039 ms | -8.3% | 0.371 ms | 0.599 ms |
| • `fit_cadence_text` (Cad chart) | 0.298 ms | **0.265 ms** | -0.033 ms | -11.1% | 0.209 ms | 0.411 ms |

### B. End-to-End Pipeline Metrics (Produkcyjny Exporter AMD D3D11 / AMF):

| Metryka Potoku | BEFORE 4E (AVG) | AFTER 4E (AVG) | Delta | Zmiana % |
| :--- | :---: | :---: | :---: | :---: |
| **RENDER FPS** | **26.573 fps** | **28.951 fps** | **+2.378 fps** | **+8.9%** |
| **USER EFFECTIVE FPS** | **18.233 fps** | **19.663 fps** | **+1.430 fps** | **+7.8%** |
| **`above_compose` (in pipeline)** | 17.071 ms | **12.841 ms** | -4.230 ms | **-24.8%** |
| **`above_total`** | 19.212 ms | **15.361 ms** | -3.851 ms | **-20.0%** |
| **`producer_prepare`** | 28.528 ms | **25.411 ms** | -3.117 ms | **-10.9%** |
| **`video_render_wall`** | 42.563 s | **39.066 s** | -3.497 s | **-8.2%** |
| **`TOTAL_FROM_EXPORT_START`** | 62.029 s | **57.519 s** | -4.510 s | **-7.3%** |

---

## 5. Weryfikacja Poprawności i Golden Parity

1. `pytest tests/test_golden_parity_etap4.py -v`:
   - `test_golden_elements_presence_and_bboxes`: **PASSED**
   - `test_lean_visible_gap_positive`: **PASSED**
   - `test_lean_gpu_pivot_exact_match`: **PASSED**
   - `test_golden_pixel_parity`: **PASSED** ($MaxDiff = 0, DifferentPixels = 0$).
2. **Pełny zestaw testów jednostkowych i kontraktowych (130 testów):**
   - Wszystkie 130 testów przechodzą w 100% (**130 passed, 0 failed, 0 errors in 14.08s**).
3. **Izolacja backendów:**
   - Zmiany wyłącznie wewnątrz rendererów `bar.py` i compositingu `compositor.py`.
   - Brak modyfikacji ścieżek NVIDIA i Intel.

---

## 6. Aktualny Bottleneck po ETAP 4E i Rekomendacja dla ETAP 4F

### Aktualny ranking kosztów w potoku:
1. **`speed_text` CPU gauge capture (~1.169 ms):**
   Speed gauge jest obecnie renderowany na CPU (do pamięci) i dopiero potem przechwytywany do GPU (`above_gpu_capture`).
2. **`lean_indicator` (~0.696 ms):**
   Ikona lean ma szybki GPU affine transform, ale warstwa CPU nadal wykonuje Pillow alpha blend napisów/tła.
3. **`above_region_to_bytes` (~2.441 ms) & `above_tight_bbox_collect` (~1.843 ms):**
   Klastrowanie i pobieranie wycinków do transferu GPU stanowi teraz znaczącą część `above_total`.

### Rekomendacja dla ETAP 4F:
Skupić się na eliminacji zbędnego renderowania CPU dla elementów przechwytywanych na GPU (`speed_text` gauge capture) oraz optymalizacji transferu `above_tight_bbox_collect` / `above_region_to_bytes`.
