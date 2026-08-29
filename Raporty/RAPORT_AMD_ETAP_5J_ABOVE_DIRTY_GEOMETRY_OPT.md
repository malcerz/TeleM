# RAPORT: AMD ETAP 5J — ABOVE DIRTY GEOMETRY / TILE COMPOSITOR OPTIMIZATION

**Data:** 2026-08-28  
**Backend:** AMD (Ryzen 7 7730U / Radeon Graphics — 8C/16T, 32GB RAM UMA)  
**Gałąź:** `amd-render`  
**Status:** COMPLETE (LOCAL PASS: -39.3% dirty pixels / bytes, MaxDiff = 0, Preview 6/6 PASS)

---

## 1. Executive Summary

W ramach etapu **ETAP 5J**:
1. **Pełny audyt geometrii i klatka-po-klatce trace (1131 klatek):**
   - Zbadano strukturę prostokątów dirty w warstwie CPU ABOVE dla kanonicznego layoutu `cycling_dashboard_v10.json`.
   - Ustalono, że wykluczenia GPU (Speed Gauge AFTER-MAP, Chart HR/Cadence GPU_SPLIT, GPU Track-Up Map, Lean GPU) działają w 100% poprawnie i wnoszą **0 pikseli** do dirty ABOVE.
   - 7 aktywnych widgetów CPU ABOVE (`slope_text`, `compass`, `alt_visual`, `fit_curVpower_text`, `temp_text`, `iso_text`, `exposure_text`) zajmuje naturalnie łącznie zaledwie **371,785 px (1.42 MB)**.
2. **Identyfikacja narzutu klastrowania (Clustering Bloat):**
   - Poprzedni algorytm klastrowania geometrycznego (`pad=16`, `merge_dist=32`, łączenie po odległości środków) sztucznie rozszerzał obszar dirty do **612,717 px (2.34 MB)** (+18.3% do +39.3% pustych pikseli).
   - Wykazano brak jakichkolwiek gigantycznych prostokątów (`>1M px` = 0 wystąpień w warstwie ABOVE).
3. **Implementacja i porównanie strategii dirty:**
   - **Wariant A (Distance Merge Reference):** 612k px, 2.34 MB/frame.
   - **Wariant B (Area-Cost Merge):** 371k px, 1.42 MB/frame.
   - **Wariant C (Discrete Tight Rects — Zwycięzca):** 7 bezpośrednich prostokątów o zerowym paddingu i zerowym narzucie klastrowania -> **371,785 px (1.42 MB/frame)**.
4. **Weryfikacja parzystości (Golden Parity) i podglądu mapy:**
   - Test wieloklatkowy (0, 50, 100, 300, 500, 750, 900, 965, 1130) potwierdził **MaxDiff = 0, DifferentPixels = 0** (100% zgodności bitowej).
   - Preview Map Matrix: **6/6 testów ALL PASS**.
5. **Wyniki i klasyfikacja:**
   - **Redukcja przesyłanych bajtów UMA:** z **2.34 MB** do **1.42 MB** (**-39.3%**).
   - **Redukcja pikseli dirty:** z **612,717 px** do **371,785 px** (**-39.3%**).
   - **Czas uploadu D3D11 (`above_region_upload`):** zredukowany do **0.879 ms**.
   - **Klasyfikacja:** **STRUCTURAL LOCAL PASS** (zgodnie z Sekcją 33: $\ge 25\%$ mniej dirty pixels/bytes, 0 regresji, MaxDiff=0).

---

## 2. Dirty Baseline vs Discrete Tight

| Metryka | Distance Merge (BEFORE) | Discrete Tight (AFTER) | Zmiana |
| :--- | :--- | :--- | :--- |
| **Prostokąty na klatkę** | **6.00** | **7.00** | +1.00 |
| **Piksele dirty na klatkę** | **612,717 px** | **371,785 px** | **-240,932 px (-39.3%)** |
| **Pokrycie ekranu 4K** | **7.38%** | **4.48%** | **-2.90 pp** |
| **Bajty na klatkę** | **2,450,868 B (2.34 MB)** | **1,487,140 B (1.42 MB)** | **-0.92 MB (-39.3%)** |
| **Pasmo UMA przy 40 FPS** | **~93.6 MB/s** | **~56.8 MB/s** | **-36.8 MB/s (-39.3%)** |
| **UpdateSubresource calls** | **6.00** | **7.00** | +1.00 |
| **above_region_upload (avg)**| **0.992 ms** | **0.879 ms** | **-0.113 ms (-11.4%)** |
| **above_total (avg)** | **10.219 ms** | **9.923 ms** | **-0.296 ms (-2.9%)** |
| **above_compose (avg)** | **8.877 ms** | **8.636 ms** | **-0.241 ms (-2.7%)** |

---

## 3. Per-Widget Dirty Attribution (1131 Klatek)

| Ranga | Widget | Bbox Bounding Area | Tight Area | Udział % w ABOVE Dirty |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `slope_text` | 146,718 px | 115,971 px | **31.2%** |
| **2** | `compass` | 139,876 px | 88,209 px | **23.7%** |
| **3** | `alt_visual` | 131,200 px | 87,640 px | **23.6%** |
| **4** | `fit_curVpower_text` | 92,837 px | 72,705 px | **19.6%** |
| **5** | `temp_text` | 3,645 px | 3,645 px | **1.0%** |
| **6** | `iso_text` | 3,015 px | 3,015 px | **0.8%** |
| **7** | `exposure_text` | 600 px | 600 px | **0.2%** |

---

## 4. Coverage Efficiency

- **Średnia efektywność (piksele niezerowe / obszar bbox):** **30.73%**
- **Mediana efektywności:** **21.95%**
- **P10:** **3.35%**
- **P90:** **95.00%**
- **Wystąpienia prostokątów >1M px:** **0 / 3393**

---

## 5. Max-Rects Ablation Matrix

| Max Rects | Distance Merge Rects | Distance Merge Pixels | Distance Merge MB | Area-Cost Pixels | Area-Cost MB |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **4** | 4.00 | 636,732 px | 2.43 MB | 531,505 px | 2.03 MB |
| **8** | 6.00 | 612,717 px | 2.34 MB | 371,785 px | 1.42 MB |
| **12** | 6.00 | 612,717 px | 2.34 MB | 371,785 px | 1.42 MB |
| **16** | 6.00 | 612,717 px | 2.34 MB | 371,785 px | 1.42 MB |
| **24** | 6.00 | 612,717 px | 2.34 MB | 371,785 px | 1.42 MB |
| **32** | 6.00 | 612,717 px | 2.34 MB | 371,785 px | 1.42 MB |

---

## 6. Final TOP 10 Bottlenecks (Recalculated)

| Ranga | Komponent / Obszar | Mediana (ms) | % Actual Render Interval (24.965ms) | % Video Period (33.367ms) |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `above_compose` (Pillow raster) | **8.512 ms** | **34.1%** | 25.5% |
| **2** | `consumer_native_call` (D3D11 GPU) | **7.853 ms** | **31.5%** | 23.5% |
| **3** | `above_region_to_bytes` (Direct pointer) | **1.171 ms** | **4.7%** | 3.5% |
| **4** | `map_cpu_upload` (Map tile prep) | **0.890 ms** | **3.6%** | 2.7% |
| **5** | `above_region_upload` (D3D11 upload) | **0.879 ms** | **3.5%** | 2.6% |
| **6** | `above_exact_crop` | **0.847 ms** | **3.4%** | 2.5% |
| **7** | `MF ReadSample/decode availability` | **0.658 ms** | **2.6%** | 2.0% |
| **8** | `above_tight_bbox_collect` | **0.607 ms** | **2.4%** | 1.8% |
| **9** | `AMF submit/backpressure` | **0.352 ms** | **1.4%** | 1.1% |
| **10**| `VideoProcessor CPU submit` | **0.240 ms** | **1.0%** | 0.7% |
