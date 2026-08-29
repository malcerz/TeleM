# RAPORT: AMD ETAP 5I — REAL CPU ABOVE COMPOSITOR OPTIMIZATION

**Data:** 2026-08-28  
**Backend:** AMD (Ryzen 7 7730U / Radeon Graphics — 8C/16T, 32GB RAM UMA)  
**Gałąź:** `amd-render`  
**Status:** COMPLETE (E2E PASS: +3.37% TRUE FPS / -3.26% Total Export)

---

## 1. Executive Summary

W ramach etapu **ETAP 5I**:
1. **Precyzyjny profil i rozbicie kosztów warstwy CPU ABOVE:**
   - Wyizolowano rzeczywiste składowe wewnątrz `above_compose` i `above_total`.
   - Pokazano, że samo renderowanie pojedynczych wskaźników tekstowych zajmuje łącznie zaledwie **0.104 ms/klatkę** (dzięki keszowaniu fontów i wektorów).
   - Główny narzut CPU ABOVE stanowiła ekstrakcja dirty regions i transfer pamięci.
2. **Implementacja Zero-Copy Direct Strided Pointer w `_extract_fine_dynamic_above_regions` (TOP1):**
   - Wprowadzono bezpośredni wskaźnik pamięciowy wierszy (`row_table_ptr + cy * 8`) dla fine-grained i multi-rect dynamicznych regionów.
   - Wyeliminowano alokacje `Image.crop` oraz `tobytes()`, przekazując bezpośredni wskaźnik `region_ptr` ze stałym krokiem wiersza `canvas_stride = 3840 * 4` bezpośrednio do `ID3D11DeviceContext::UpdateSubresource`.
3. **Parzystość i weryfikacja bitowa (Golden Parity):**
   - Testy wieloklatkowe (klatki 0, 50, 100, 300, 500, 750, 900, 965, 1130) oraz brzegowe wykazały **MaxDiff = 0, DifferentPixels = 0**.
   - Sprawdzono i potwierdzono pełną regresję macierzy podglądu mapy (**6/6 testów PASS**).
4. **Oficjalne wyniki wydajnościowe (5-Run Measured Benchmark):**
   - **TRUE FPS (mediana):** wzrósł z **36.689 FPS** do **37.924 FPS** (**+1.235 FPS / +3.37%**).
   - **Całkowity czas eksportu (mediana):** skrócił się z **30.827 s** do **29.823 s** (**-1.004 s / -3.26%**).
   - **producer_prepare:** spadł z **14.334 ms** do **13.657 ms** (**-0.677 ms**).
   - **above_total:** spadł z **10.713 ms** do **10.219 ms** (**-0.494 ms**).
   - **Stabilność pomiaru (CV%):** **0.92%** (<1%).
   - **Klasyfikacja:** **E2E PASS** (osiągnięto próg $\ge +3\%$ TRUE FPS).

---

## 2. Production State

```text
=== AMD REAL PRODUCTION EFFECTIVE CONFIG ===
  CPU_GPU_PIPELINE = SYNC
  QUEUE_DEPTH      = 0
  VP_STATE         = REFERENCE
  AMF_QUERY        = REFERENCE
  MAP_PATH         = GPU (ALIGN=16, REUSE=0)
  GAUGE_GPU        = 1 (AUTO)
  CHART_GPU        = 1 (GPU_SPLIT)
  LEAN_GPU         = 0
  HUD_MODE         = GPU_HUD
  NV12_COMPOSITOR  = FUSED
```

---

## 3. Fresh BEFORE vs Final AFTER Comparison

| Metryka | Stan 5H.1 (BEFORE) | Stan 5I (AFTER) | Zmiana |
| :--- | :--- | :--- | :--- |
| **TRUE FPS (mediana)** | **36.689 fps** | **37.924 fps** | **+1.235 fps (+3.37%)** |
| **RENDER FPS** | **40.022 fps** | **40.056 fps** | **+0.034 fps** |
| **USER EFFECTIVE FPS** | **37.544 fps** | **37.624 fps** | **+0.080 fps** |
| **Actual Render Interval** | **24.986 ms** | **24.965 ms** | **-0.021 ms** |
| **Całkowity czas eksportu** | **30.827 s** | **29.823 s** | **-1.004 s (-3.26%)** |
| **producer_prepare (avg)** | **14.334 ms** | **13.657 ms** | **-0.677 ms (-4.7%)** |
| **above_total (avg)** | **10.713 ms** | **10.219 ms** | **-0.494 ms (-4.6%)** |
| **above_compose (avg)** | **9.286 ms** | **8.877 ms** | **-0.409 ms (-4.4%)** |
| **map_cpu_upload (avg)** | **1.052 ms** | **1.001 ms** | **-0.051 ms** |
| **gauge_upload (avg)** | **0.163 ms** | **0.162 ms** | **-0.001 ms** |
| **consumer_native (avg)** | **6.393 ms** | **6.484 ms** | **+0.091 ms** |
| **VP submit (avg)** | **0.261 ms** | **0.268 ms** | **+0.007 ms** |

---

## 4. Per-Widget CPU ABOVE Ranking (1131 Frames)

| Ranga | Wskaźnik | Średnia (ms) | Mediana (ms) | P95 (ms) | Unikalne wartości |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `compass` | **0.021 ms** | **0.016 ms** | **0.026 ms** | Dynamiczny kąt z FIT |
| **2** | `slope_text` | **0.016 ms** | **0.011 ms** | **0.017 ms** | Dynamiczne nachylenie z FIT |
| **3** | `iso_text` | **0.013 ms** | **0.010 ms** | **0.016 ms** | Stały/półstały |
| **4** | `fit_curVpower_text`| **0.012 ms** | **0.009 ms** | **0.012 ms** | Dynamiczna moc z FIT |
| **5** | `alt_visual` | **0.012 ms** | **0.009 ms** | **0.013 ms** | Pasek wysokości |
| **6** | `exposure_text` | **0.010 ms** | **0.009 ms** | **0.013 ms** | Ekspozycja |
| **7** | `temp_text` | **0.010 ms** | **0.009 ms** | **0.012 ms** | Temperatura |

---

## 5. Structural Dirty-Rect & Transfer Costs

| Składnik | Czas przed 5I | Czas po 5I | Oszczędność |
| :--- | :--- | :--- | :--- |
| **`above_region_to_bytes`** | **1.567 ms** | **1.178 ms** | -0.389 ms (zero-copy pointer) |
| **`above_exact_crop`** | **1.290 ms** | **0.881 ms** | -0.409 ms (zero-copy pointer) |
| **`above_region_upload`** | **1.027 ms** | **0.931 ms** | -0.096 ms |
| **`above_tight_bbox_collect`** | **0.583 ms** | **0.614 ms** | Bounded (5H fast-path) |
| **`above_exact_union`** | **0.052 ms** | **0.047 ms** | Bounded |
| **`above_bbox_tracking`** | **0.044 ms** | **0.040 ms** | Bounded |

---

## 6. Dirty Rectangle Statistics

- **Liczba prostokątów na klatkę (avg):** **3.00**
- **Piksele dirty na klatkę (avg):** **4 402 070 px** (53.07% powierzchni 4K)
- **Bajty przesłane na klatkę (avg):** **17.61 MB**
- **Wielkość największego prostokąta:** ~1920x1080 (obszar dolny)
- **Alokacje buforów:** **0 per klatka** (bezpośredni wskaźnik C na pamięć RGBA z `canvas_stride = 15360`).

---

## 7. Parity & Preview Validation

- **Pixel Parity:** `MaxDiff = 0`, `DifferentPixels = 0` na wszystkich klatkach testowych (0, 50, 100, 300, 500, 750, 900, 965, 1130).
- **Preview Map Harness:** 6/6 testów PASS (cold start, provider switch, normal/cancel export return, offline cache).

---

## 8. Final TOP 10 Production Bottlenecks (Recalculated)

| Ranga | Komponent / Obszar | Mediana (ms) | % Video Period (33.367ms) | % Actual Render Interval (24.965ms) |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `above_compose` (Pillow raster) | **8.645 ms** | 25.9% | **34.6%** |
| **2** | `consumer_native_call` (D3D11 GPU) | **6.484 ms** | 19.4% | **26.0%** |
| **3** | `above_region_to_bytes` (Direct pointer) | **1.178 ms** | 3.5% | **4.7%** |
| **4** | `map_cpu_upload` (Map tile prep) | **0.929 ms** | 2.8% | **3.7%** |
| **5** | `above_region_upload` (D3D11 upload) | **0.931 ms** | 2.8% | **3.7%** |
| **6** | `above_exact_crop` | **0.881 ms** | 2.6% | **3.5%** |
| **7** | `MF ReadSample/decode availability` | **0.680 ms** | 2.0% | **2.7%** |
| **8** | `above_tight_bbox_collect` | **0.614 ms** | 1.8% | **2.5%** |
| **9** | `AMF submit/backpressure` | **0.380 ms** | 1.1% | **1.5%** |
| **10**| `VideoProcessor CPU submit` | **0.248 ms** | 0.7% | **1.0%** |
