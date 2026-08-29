# RAPORT: AMD ETAP 5H.1 — PRODUCTION CONSOLIDATION, PREVIEW VALIDATION, 5H ACCEPTANCE & CLEAN BASELINE

**Data:** 2026-08-28  
**Backend:** AMD (Ryzen 7 7730U / Radeon Graphics — 8C/16T, 32GB RAM UMA)  
**Gałąź:** `amd-render`  
**Status:** COMPLETE

---

## 1. Executive Summary

W ramach etapu **ETAP 5H.1**:
1. **Pełna walidacja użytkowa podglądu mapy (Preview Map Validation):**
   - Wszystkie 6 testów zautomatyzowanej macierzy w `scratch/test_etap5g2_preview_map_matrix.py` zakończyły się wynikiem **PASS**.
   - Przetestowano: cold start, przełączanie dostawców (`light_all` ↔ `satellite`), powrót z normalnego eksportu, powrót z anulowanego eksportu, przełączanie presetów oraz tryb offline z kafelkami z cache.
2. **Audyt exception-safety blokady sieciowej mapy (`map_network_allowed`):**
   - Odblokowanie sieci (`set_map_network_allowed(True)`) oraz sprzątanie zasobów (`_cleanup_native_resources()`) są bezwzględnie umieszczone w bloku `finally` komendy eksportu `export_amd_native_d3d11`. Żadna ścieżka błędu, anulowania ani wyjątku nie pozostawia zablokowanego podglądu w GUI.
3. **Oficjalne źródło prawdy konfiguracji produkcyjnej AMD:**
   - Wywołanie produkcyjne (bez zmiennych środowiskowych benchmarku) uruchamia potok:
     - `CPU_GPU_PIPELINE = SYNC`
     - `QUEUE_DEPTH = 0` (direct in-thread execution)
     - `VP_STATE = REFERENCE`
     - `AMF_QUERY = REFERENCE`
     - `MAP_PATH = GPU` (`AMD_MAP_ALIGN = 16`, `AMD_MAP_SOURCE_REUSE = 1`)
     - `GAUGE_GPU = 1 (AUTO)` (AFTER-MAP GPU BlendGauge, full refresh co 120 klatek)
     - `CHART_GPU = 1 (GPU_SPLIT)` (AFTER-MAP native D3D11 charts)
     - `HUD_MODE = GPU_HUD`
     - `NV12_COMPOSITOR = FUSED`
4. **Weryfikacja decyzji konfiguracyjnej 5G.2 (A/B):**
   - Tryb `SYNC` zapewnia identyczną wydajność E2E jak `ASYNC` (różnica True FPS poniżej 0.15%), eliminując narzut wątkowy i opóźnienia VideoProcessor Submit (0.26 ms w SYNC vs 14.14 ms w ASYNC). `SYNC` pozostaje domyślnym standardem produkcyjnym.
5. **Weryfikacja danych dynamicznych kompasu i nachylenia:**
   - W kanonicznym presecie `presets/cycling_dashboard_v10.json` wskaźniki `compass` i `slope_text` mają ustawione źródło `source="fit"`.
   - Dla klatek 0..965: **396 unikalnych kątów**, **199 unikalnych rastrów** kompasu; **7 unikalnych nachyleń**.
   - Dla pełnego przebiegu 1131 klatek: **561 unikalnych kątów**, **247 unikalnych rastrów** kompasu; **12 unikalnych nachyleń**.
6. **Audyt korzyści, parzystości i pamięci optymalizacji 5H TOP1:**
   - Zastąpienie `overlay.getchannel("A").getbbox()` przez `overlay.getbbox()` (dla czystych zer alfa) wyeliminowało **14 703 alokacje** pośrednich obiektów obrazów `Image` w skali szarości na 1131 klatkach (**100% redukcji alokacji kanału alfa**).
   - Hit rate ścieżki szybkiej: **100.0%** (13/13 wskaźników na klatkę).
   - Parzystość pikselowa: **MaxDiff = 0, DifferentPixels = 0** na wszystkich klatkach testowych (0, 50, 100, 300, 500, 750, 900, 965, 1130) oraz przypadkach brzegowych.
   - Pamięć: słowniki `_WIDGET_CLEAN_TRANSPARENCY` (42 wpisy) i `_WIDGET_ALPHA_MIN` (43 wpisy) są ściśle ograniczone stałą liczbą wskaźników w layoucie; atrybut `overlay._alpha_bbox` jest zwalniany automatycznie przez GC wraz z obiektem `Image`.
   - Klasyfikacja: **LOCAL PASS / SAFE MICRO-OPT** (zostaje w kodzie produkcyjnym: **KEEP = YES**).
7. **Świeży 5-biegowy kanoniczny baseline produkcyjny:**
   - **TRUE FPS (mediana):** **36.689 FPS** (średnia 36.694 FPS, CV = 1.67%).
   - **RENDER FPS:** **40.022 FPS**.
   - **USER EFFECTIVE FPS:** **37.544 FPS**.
   - **Całkowity czas eksportu (mediana):** **30.827 s**.

---

## 2. Preview Map Validation Matrix (Automated Harness)

| Test Case | Warunek wejściowy | Oczekiwane zachowanie | Wynik |
| :--- | :--- | :--- | :--- |
| **TEST 1** | Cold start + load preset | Mapa widoczna, brak stałego placeholdera | **PASS** |
| **TEST 2** | Switch: satellite → light_all → satellite | Synchronizacja `MapContext`, poprawny styl | **PASS** |
| **TEST 3** | Normal export return | `map_network_allowed == True`, podgląd aktywny | **PASS** |
| **TEST 4** | Cancel export return | `map_network_allowed == True`, podgląd aktywny | **PASS** |
| **TEST 5** | Switch preset → return to canonical | Płynne ładowanie mapy | **PASS** |
| **TEST 6** | Offline mode (cached tiles) | Natychmiastowy render z lokalnego cache | **PASS** |

---

## 3. Real Production Effective Configuration

```text
=== AMD REAL PRODUCTION EFFECTIVE CONFIG ===
  CPU_GPU_PIPELINE = SYNC
  QUEUE_DEPTH      = 0
  VP_STATE         = REFERENCE
  AMF_QUERY        = REFERENCE
  MAP_PATH         = GPU
  MAP_ALIGN        = 16
  GAUGE_GPU        = 1 (AUTO)
  CHART_GPU        = 1 (GPU_SPLIT)
  LEAN_GPU         = 0
  HUD_MODE         = GPU_HUD
  NV12_COMPOSITOR  = FUSED
```

---

## 4. 5H TOP1 Audit & Metrics

| Metryka | Przed 5H | Po 5H | Zmiana |
| :--- | :--- | :--- | :--- |
| **above_tight_bbox_collect (mediana)** | **0.589 ms** | **0.519 ms** | **-0.070 ms (-11.9%)** |
| **Alokacje kanału alfa na bieg (1131f)** | **14 703** | **0** | **-14 703 (-100%)** |
| **Fast-path Hit Rate** | 0.0% | **100.0%** (13/13 wskaźników) | **+100.0%** |
| **Parzystość pikselowa** | Reference | Exact | **MaxDiff = 0** |
| **Pamięć / Wycieki** | Bounded | Bounded (42 klucze) | **Zero wycieków** |
| **Klasyfikacja** | — | — | **LOCAL PASS / SAFE MICRO-OPT** |
| **Decyzja** | — | — | **KEEP (YES)** |

---

## 5. Final Production Baseline (5 Measured Runs, Clean Environment)

```text
==================================================
=== ETAP 5H.1 FINAL PRODUCTION 5-RUN BASELINE ===
==================================================
TRUE FPS:           36.694 fps (mediana 36.689, min 36.072, max 37.510, CV 1.67%)
RENDER FPS:         40.022 fps
USER EFFECTIVE FPS: 37.544 fps

Video Render Wall:  28.259 s
Mux Wall:            0.741 s
Total Export Wall:  30.829 s   (mediana 30.827 s)

Producer Prepare:   14.334 ms/frame (mediana 14.033 ms)
Above Total:        10.713 ms/frame (mediana 10.500 ms)
Above Compose:       9.286 ms/frame (mediana  9.107 ms)
Tight Bbox Collect:  0.583 ms/frame (mediana  0.580 ms)
Map CPU Upload:      1.052 ms/frame (mediana  1.021 ms)
Gauge Upload:        0.163 ms/frame (mediana  0.164 ms)
Consumer Native:     6.393 ms/frame (mediana  6.580 ms)
VP Submit (CPU):     0.261 ms/frame (mediana  0.260 ms)
AMF Submit:          0.430 ms/frame (mediana  0.428 ms)
AMF Query:           0.156 ms/frame (mediana  0.154 ms)
==================================================
```

---

## 6. Fresh TOP 10 Production Bottleneck Ranking

| Ranga | Komponent / Obszar | Typ | Średnia (ms) | Mediana (ms) | P95 (ms) | % interwału klatki (33.3ms) | Wpływ na ścieżkę krytyczną |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `above_compose` (Pillow raster) | CPU | **9.286 ms** | **9.107 ms** | **13.619 ms** | 27.3% | Bezpośredni (synchroniczny render tekstu na 4K canvas) |
| **2** | `consumer_native_call` (D3D11/GPU) | GPU/Sync | **6.393 ms** | **6.580 ms** | **13.256 ms** | 19.8% | Złożenie warstw GPU i synchronizacja D3D11 |
| **3** | `above_region_to_bytes` | CPU | **1.567 ms** | **1.438 ms** | **2.437 ms** | 4.3% | Ekstrakcja pamięci dirty rect do bufora |
| **4** | `above_exact_crop` | CPU | **1.290 ms** | **1.210 ms** | **1.992 ms** | 3.6% | Kadrowanie bounding boxu dirty rect z płótna |
| **5** | `map_cpu_upload` | CPU | **1.052 ms** | **1.021 ms** | **1.907 ms** | 3.1% | Przygotowanie kafelka mapy dla GPU |
| **6** | `above_region_upload` | Native | **1.027 ms** | **0.953 ms** | **1.541 ms** | 2.9% | D3D11 `UpdateSubresource` dla prostokątów dirty rect |
| **7** | `MF ReadSample/decode` | HW Decode| **0.961 ms** | **0.618 ms** | **1.217 ms** | 1.9% | Dekodowanie klatek 4K HEVC przez D3D11VA |
| **8** | `above_tight_bbox_collect` | CPU | **0.583 ms** | **0.580 ms** | **1.063 ms** | 1.7% | Zbieranie bounding boxów wklejanych wskaźników |
| **9** | `AMF submit/backpressure` | HW Encode| **0.430 ms** | **0.428 ms** | **0.552 ms** | 1.3% | Przekazanie klatki NV12 do enkodera AMF HEVC |
| **10**| `VideoProcessor CPU submit` | Native | **0.261 ms** | **0.260 ms** | **0.347 ms** | 0.8% | Wywołanie operacji Blt w VideoProcessorze |
