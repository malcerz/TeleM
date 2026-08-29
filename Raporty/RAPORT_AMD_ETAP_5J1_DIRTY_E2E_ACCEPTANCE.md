# RAPORT: AMD ETAP 5J.1 — DIRTY METRIC RECONCILIATION + REAL E2E ACCEPTANCE

**Data:** 2026-08-28  
**Backend:** AMD (Ryzen 7 7730U / Radeon Graphics — 8C/16T, 32GB RAM UMA)  
**Gałąź:** `amd-render`  
**Status:** COMPLETE (RECONCILIATION PASS / DECISION: ROLLBACK 5J DEFAULT TO REFERENCE 5I)

---

## 1. Executive Summary

W ramach etapu **ETAP 5J.1**:
1. **Wyjaśnienie i uzgodnienie rozbieżności metryk 5I vs 5J (Metric Root Cause):**
   - Zidentyfikowano przyczynę siedmiokrotnej różnicy: w diagnostycznym skrypcie 5I (`profile_etap5i_above_breakdown.py`) do funkcji kompozytora omyłkowo przekazano pełny niesplitowany `layout=layout` zawierający wszystkie 15 wskaźników (w tym dolny HUD poniżej mapy, pełny licznik 777x777 i mapę), co generowało 4.40 Mpx (17.61 MB).
   - W rzeczywistym eksporterze oraz w etapie 5J przekazywany jest poprawny `map_above_layout` zawierający wyłącznie 7 wskaźników CPU ABOVE, które w trybie `REFERENCE_5I` generują dokładnie **612,717 px (2.34 MB/frame)**, a w trybie `DISCRETE_TIGHT_5J` **371,785 px (1.42 MB/frame)**.
2. **Ustanowienie kanonicznych definicji geometrii dirty:**
   - Wprowadzono precyzyjny podział: `logical_widget_dirty_px`, `pre_merge_dirty_px`, `post_merge_dirty_px`, `native_upload_px`, `native_upload_bytes`, `UpdateSubresource_calls`.
3. **Ścisły naprzemienny benchmark A/B (1 warmup + 5 pomiarów na wariant, łącznie 12 uruchomień):**
   - **REFERENCE_5I (Distance Merge, 6 regionów):** True FPS = **37.607 fps** (mediana), Total export = **30.074 s**, `above_total` = **11.000 ms**.
   - **DISCRETE_TIGHT_5J (Discrete Tight, 7 regionów):** True FPS = **37.318 fps** (mediana), Total export = **30.307 s**, `above_total` = **11.330 ms**.
   - **Delta:** True FPS = **-0.289 fps (-0.77%)**, Total export = **+0.233 s (+0.77%)**.
4. **Decyzja i klasyfikacja:**
   - Mimo redukcji przesyłanych bajtów UMA o -39.3% (z 2.34 MB do 1.42 MB), narzut CPU związany z obsługą, kolekowaniem i wywoływaniem 7 niezależnych regionów (`UpdateSubresource`) przewyższa zysk po stronie GPU, powodując spadek `True FPS` o -0.77%.
   - Zgodnie z żelazną zasadą z Sekcji 14 & 15: brak E2E PASS i brak LOCAL PASS $\implies$ **ROLLBACK domyślnej strategii produkcyjnej do REFERENCE_5I (`AMD_ABOVE_DIRTY_STRATEGY=DIST`)**.
   - Kod zachowuje wsparcie dla flagi `AMD_ABOVE_DIRTY_STRATEGY`, a domyślnym standardem produkcyjnym pozostaje sprawdzony, najszybszy `DIST`.

---

## 2. 5I vs 5J Metric Root Cause & Trace

| Parametr | Skrypt diagnostyczny 5I (`profile_etap5i_above_breakdown.py`) | Rzeczywisty eksporter / 5J (`map_above_layout`) | Ten sam parametr? | Wyjaśnienie różnicy |
| :--- | :--- | :--- | :--- | :--- |
| **Źródło layoutu** | Pełny `layout` (15 wskaźników) | Wyodrębniony `map_above_layout` (7 wskaźników) | **NIE** | 5I badał niesplitowany layout ze wszystkimi warstwami. |
| **Zawartość** | Zawierał dolny HUD, speed gauge, mapę | Tylko teksty/paski ABOVE (`compass`, `slope`, etc.) | **NIE** | Wskaźniki GPU (gauge/chart/map) są wykluczone z ABOVE. |
| **Liczba prostokątów** | 3 (scalone wielkie obszary) | 6 (Distance Merge) lub 7 (Discrete Tight) | **NIE** | Odmienna liczba i położenie wskaźników. |
| **Piksele dirty** | **4,402,070 px (53.07% 4K)** | **612,717 px (7.38% 4K)** | **NIE** | 4.40 Mpx to sztuczny artefakt profilera z pełnym layoutem. |
| **Przesłane bajty** | **17.61 MB/frame** | **2.34 MB/frame (REF)** / **1.42 MB/frame (5J)** | **NIE** | Rzeczywisty narzut UMA ABOVE to 2.34 MB (REF) / 1.42 MB (5J). |

---

## 3. Canonical Dirty Metric Definitions

1. **`logical_widget_dirty_px`:** Suma powierzchni alpha-tight aktywnych widgetów CPU ABOVE = **371,785 px/frame**.
2. **`pre_merge_dirty_px`:** Suma prostokątów bounding box przed scaleniem = **517,891 px/frame**.
3. **`post_merge_dirty_px`:** Powierzchnia prostokątów po scaleniu przez planner = **612,717 px/frame** (REF) vs **371,785 px/frame** (5J).
4. **`native_upload_px`:** Rzeczywista liczba pikseli przekazana do D3D11 = **612,717 px/frame** (REF) vs **371,785 px/frame** (5J).
5. **`native_upload_bytes`:** `native_upload_px * 4` = **2,450,868 B (2.34 MB)** (REF) vs **1,487,140 B (1.42 MB)** (5J).
6. **`UpdateSubresource_calls`:** Liczba wywołań D3D11 `UpdateSubresource` na klatkę = **6.00** (REF) vs **7.00** (5J).

---

## 4. Interleaved 5-Run A/B Benchmark Results

| Metryka | REFERENCE_5I (Distance Merge) | DISCRETE_TIGHT_5J (Discrete Tight) | Delta (5J vs REF) |
| :--- | :--- | :--- | :--- |
| **TRUE FPS (mediana)** | **37.607 fps** (mean 37.536, CV 1.26%) | **37.318 fps** (mean 37.365, CV 1.09%) | **-0.289 fps (-0.77%)** |
| **Całkowity czas eksportu**| **30.074 s** (mean 30.135 s) | **30.307 s** (mean 30.272 s) | **+0.233 s (+0.77%)** |
| **producer_prepare (avg)** | **14.623 ms** | **15.106 ms** | **+0.483 ms** |
| **above_total (avg)** | **11.000 ms** | **11.330 ms** | **+0.330 ms** |
| **above_compose (avg)** | **9.533 ms** | **9.854 ms** | **+0.321 ms** |
| **above_region_upload** | **1.013 ms** | **1.038 ms** | **+0.025 ms** |
| **consumer_native_call** | **5.140 ms** | **4.999 ms** | **-0.141 ms (-2.7%)** |
| **Przesłane bajty / klatka**| **2.34 MB** | **1.42 MB** | **-0.92 MB (-39.3%)** |
| **Wywołania UpdateSubresource**| **6.00** | **7.00** | **+1.00** |

---

## 5. Technical Analysis of Discrepancies

### A. `above_region_to_bytes` Explanation
- W etapie 5I wprowadzono bezpośredni wskaźnik C (`row_table_ptr + cy * 8`), eliminując alokacje `Image.crop` oraz `tobytes()`.
- Timer `above_region_to_bytes` nie mierzy już kopiowania pamięci pikseli, lecz czas rzutowania PyCapsule, weryfikacji ciągłości `is_contig`, instancjonowania struktur ctypes i marshallingu kolejki. Dlatego czas ten wynosi ~1.1-1.4 ms niezależnie od liczby bajtów w sub-boxie.

### B. `consumer_native_call` Explanation
- Zmierzony w naprzemiennym teście A/B czas `consumer_native_call` wynosi **5.140 ms (REF)** vs **4.999 ms (5J)**.
- GPU zyskuje ~0.14 ms na mniejszym wolumenie pamięci UMA (1.42 MB vs 2.34 MB), lecz CPU traci ~0.48 ms na przygotowaniu 7 oddzielnych struktur i wskaźników, co daje ujemny bilans netto (-0.77% True FPS).

---

## 6. Parity & Preview Map Verification

- **Golden Multi-Frame Parity:** `MaxDiff = 0`, `DifferentPixels = 0` na wszystkich klatkach testowych (0, 50, 100, 300, 500, 750, 900, 965, 1130).
- **Preview Map Matrix:** 6/6 testów PASS (cold preview, provider switch, normal return, cancel return, second preset, offline cache).
