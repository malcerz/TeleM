# RAPORT AMD ETAP 3G — POST-MULTI-RECT PRODUCER AUDIT + NEXT CPU BOTTLENECK OPTIMIZATION

Data: 2026-08-26  
Backend: `AMD_NATIVE_D3D11`  
Konfiguracja produkcyjna: `AMD_ABOVE_MULTI_RECT=1` (Production Default: **ON**), `AMD_LEAN_GPU=0` (Production Default: **OFF**), `AMD_GPU_MAP_ROTATE=1`, `AMD_AFTER_MAP_CHART_GPU=1`, `AMD_AFTER_MAP_GAUGE_GPU=1`, `AMD_NATIVE_DIAGNOSTICS=0`.  
GPU Extra Shaders: **0** | GPU Extra Compositor Passes: **0** | GPU Extra Textures: **0**

---

## 1. Production Default Baseline (AMD_LEAN_GPU=0) vs GPU-Lean Baseline (AMD_LEAN_GPU=1)

Po wdrożeniu multi-rect dirty upload (ETAP 3E/3F) i przejściu na produkcyjny transfer ~2.52 MB/klatkę zmierzono dwa bazowe stany renderera:

| Metryka | Production Default (`AMD_LEAN_GPU=0`) | GPU-Lean Mode (`AMD_LEAN_GPU=1`) |
| :--- | :---: | :---: |
| **Canonical RENDER FPS** | **19.445 fps** (aktywny render: 26.5 fps) | **21.571 fps** (aktywny render: 32.1 fps) |
| **producer_prepare avg** | **31.175 ms** | **25.358 ms** |
| **above_compose avg** | **24.425 ms** | **17.425 ms** |
| **below_compose avg** | **2.815 ms** | **3.774 ms** |
| **multi crop + tobytes** | **2.076 ms** | **2.261 ms** |
| **consumer_native_call** | **2.246 ms** | **2.532 ms** |
| **pipeline_total** | **4.721 ms** | **5.219 ms** |

---

## 2. Frame Accounting & Inventory aktywnych widgetów CPU

### Inventory dla `def_layout.json` (3840x2160 UHD):
1. **CPU BELOW (`compose_layout`)**:
   - `time_display`: form=`time_display`, source=`gpmf` (czas wykonania: **0.006 ms**, w 100% zoptymalizowany).
2. **CPU ABOVE (`map_above_layout`)**:
   - `fit_heart_rate_text`: GPU CAPTURED (0 ms na CPU).
   - `fit_cadence_text`: GPU CAPTURED (0 ms na CPU).
   - `speed_text`: GPU CAPTURED (0 ms na CPU).
   - `iso_text`, `exposure_text`, `temp_text`: CPU RENDERED (czas wykonania: **~0.018–0.025 ms** każdy, zoptymalizowane w 3C).
   - `lean_indicator`: CPU RENDERED (w trybie default `AMD_LEAN_GPU=0` czas tight rotation to **~7.7 ms**).
   - `fit_distance_text` (Horizontal Ruler): CPU RENDERED (czas: **~0.58 ms** po in-place optymalizacji, wcześniej **~1.43 ms**).
   - `alt_text` (Vertical Ruler): CPU RENDERED (czas: **~0.73 ms** po in-place optymalizacji, wcześniej **~0.96 ms**).
3. **GPU NATIVE LAYERS**:
   - Track-Up Map (D3D11 rotation shader).
   - HR & Cadence AFTER-MAP charts (`BlendAfterMapCharts`).
   - Speed Gauge AFTER-MAP (`BlendAfterMapGauges`).

---

## 3. Per-Widget CPU Profiling & Ablation Matrix

Wyniki pomiarów bezpośrednich oraz macierzy ablacyjnej (wyłączenie pojedynczego widgetu na 300 klatkach):

| Widget | Renderer Timing AVG | Ablation Delta (Total d) | Udział w obciążeniu CPU |
| :--- | :---: | :---: | :---: |
| **`fit_distance_text` (Bar/Ruler)** | 0.58 ms | **+3.695 ms / frame** | **TOP BOTTLENECK #1** |
| **`alt_text` (Vertical Ruler)** | 0.73 ms | **+1.560 ms / frame** | **TOP BOTTLENECK #2** |
| **`time_display`** | 0.006 ms | +1.647 ms / frame | Compositor regional clear |
| **`temp_text` / Texts** | 0.025 ms | +1.218 ms / frame | Text indicators |
| **`lean_indicator`** | 7.71 ms | +0.294 ms / frame | Lean indicator |

---

## 4. Wybrany Target Optymalizacyjny: Rodzina Bar / Ruler (Horizontal & Vertical)

### Zidentyfikowany problem:
W module `src/indicators/bar.py` funkcje `_render_ruler` (pozioma linijka dystansu 2312x199 px = 1.84 MB) oraz `_render_ruler_vertical` (pionowa linijka wysokości) wykonywały co klatkę `img = base.copy()`, klonując setki kilobajtów pamięci RGBA i alokując nowe obiekty Pillow, a w linijce pionowej klucz `static_key` zmieniał się przy każdej zmianie liczby cyfr z powodu niestabilnego pomiaru `value_width`.

### Wdrożona optymalizacja:
1. **In-Place Working Buffer (`_RULER_WORKING_BUFFERS`)**:
   - Wyeliminowano per-frame `base.copy()` dla linijek poziomych i pionowych.
   - Reużywalny bufor roboczy przywraca z `base` wyłącznie obszar dirty z poprzedniej klatki (`patch = base.crop(last_dirty)`), po czym nanosi nowy znacznik i tekst wartości.
2. **Stabilny pomiar `value_width` w linijce pionowej**:
   - Zastąpiono zmienny string wartości stabilną próbką `"8888.8"`, co w 100% ustabilizowało klucz pamięci podręcznej `_RULER_BASE_CACHE` i wyeliminowało kosztowne przebudowy bazy w trakcie renderowania.

---

## 5. Microbenchmark & Pixel Parity

- **Microbenchmark (2001 wywołań)**:
  - `Horizontal Ruler`: **0.579 ms** (wcześniej ~1.43 ms -> **2.47x szybciej**)
  - `Vertical Ruler`: **0.731 ms** (wcześniej ~0.96 ms -> **1.31x szybciej**)
- **Pixel Parity (1000 klatek weryfikacji pre-encode)**:
  - `MaxDiff = 0`
  - `MAE = 0`
  - `DifferentPixels = 0`
  - **100% BIT-FOR-BIT EXACT PARITY: PASS**.

---

## 6. Alternating Long A/B Benchmark Results

Dane zarejestrowane w `Raporty/AMD_ETAP_3G/benchmark_runs.csv`:

| Run ID | Wariant | Lean GPU | Render Wall (s) | Canonical FPS | Producer (ms) | Below (ms) | Above (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `cand_1_prod_1000f` | CAND_PROD | 0 | 51.428 s | **19.445 fps** | 31.175 ms | 2.815 ms | 24.425 ms |
| `cand_2_prod_1000f` | CAND_PROD | 0 | 50.481 s | **19.809 fps** | 31.284 ms | 2.942 ms | 24.175 ms |
| `cand_3_prod_1000f` | CAND_PROD | 0 | 53.491 s | **18.695 fps** | 33.016 ms | 3.406 ms | 25.498 ms |
| `cand_gpulean_1000f` | CAND_GPULEAN | 1 | 46.359 s | **21.571 fps** | 25.358 ms | 3.774 ms | 17.425 ms |

- **Production Long A/B Median FPS (`AMD_LEAN_GPU=0`)**: **19.445 fps**
- **Optional GPU-Lean Baseline FPS (`AMD_LEAN_GPU=1`)**: **21.571 fps**

---

## 7. Status flag konfiguracyjnych & Izolacja backendów

- `AMD_ABOVE_MULTI_RECT`: **ON by default** (utrzymane).
- `AMD_LEAN_GPU`: **OFF by default** (zgodnie z wytycznymi, nie włączane automatycznie).
- `GPU Extra Shaders / Passes`: **NONE (0)**.
- Backend NVIDIA & Intel: **100% nienaruszone (neutralne)**.
