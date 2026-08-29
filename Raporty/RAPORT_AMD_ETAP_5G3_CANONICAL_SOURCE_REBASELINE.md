# RAPORT: AMD ETAP 5G.3 — CANONICAL SOURCE CORRECTION & REBASELINE

**Data:** 2026-08-28  
**Backend:** AMD (Ryzen 7 7730U / Radeon Graphics — 8C/16T, 32GB RAM UMA)  
**Gałąź:** `amd-render`  
**Status:** COMPLETE (STOP GATE 3: PASS)

---

## 1. Executive Summary

W ramach etapu **ETAP 5G.3**:
1. **Potwierdzono kontrakt źródeł danych (Source Semantics):**
   - Pole `source` w konfiguracji wskaźników jest wyborem ścisłym (jawny wybór użytkownika).
   - Nie dodano żadnych ukrytych fallbacków: `source="gpmf"` bez danych GPMF zwraca prawidłowo `--`, a `source="fit"` pobiera dane z pliku FIT.
2. **Skorygowano kanoniczny preset (`presets/cycling_dashboard_v10.json`):**
   - Dla pliku wideo `GX020079` (który nie posiada strumienia IMU/heading w GPMF, ale posiada pełne dane w pliku FIT):
     - `compass.source`: `"gpmf"` → `"fit"`
     - `slope_text.source`: `"gpmf"` → `"fit"`
3. **Przeprowadzono dowód dynamiki (Dynamic Compass & Slope Proof):**
   - **Kompas:** **562 unikalne surowe kąty** (>100 oczekiwanych), **247 unikalnych rastrów** (>50 oczekiwanych), średni koszt CPU renderera: **0.144 ms/frame**, hit rate cache kompasu: **61.8%**.
   - **Nachylenie (Slope):** **12 unikalnych wartości**, **9 unikalnych rastrów**, zakres od **0.885% do 1.925%**, średni koszt CPU renderera: **0.029 ms/frame**, hit rate cache: **98.85%**.
   - Weryfikacja wizualna klatek przejściowych (np. klatka 600: `291.87°`, klatka 900: `201.11°`, `1.925%`) potwierdziła w 100% poprawną, płynną aktualizację wskaźników.
4. **Ustanowiono NOWY 5-biegowy kanoniczny baseline produkcyjny (1131 klatek 4K):**
   - **TRUE FPS:** **37.902 FPS** (mediana **37.913 FPS**, powtarzalność CV = **0.36%**).
   - **RENDER FPS:** **40.361 FPS**.
   - **USER EFFECTIVE FPS:** **37.945 FPS**.
   - **Całkowity czas eksportu:** **29.840 s** (mediana **29.832 s**).

---

## 2. Dynamic Proof Metrics

| Wskaźnik | Źródło przed | Źródło po | Unikalne dane surowe | Unikalne rastry | Średni czas CPU | Hit Rate Cache |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Compass** | `gpmf` (brak danych, `--`) | `fit` (aktywne) | **562** (>100) | **247** (>50) | **0.144 ms** | **61.80%** (699 hit / 432 miss) |
| **Slope** | `gpmf` (brak danych, `--`) | `fit` (aktywne) | **12** (>1) | **9** (>1) | **0.029 ms** | **98.85%** (1118 hit / 13 miss) |

---

## 3. Final Canonical 5-Run Baseline (1131 frames @ 4K, Power Max Performance)

Wyniki 5 pełnych biegów pomiarowych na konfiguracji produkcyjnej (`SYNC`, `REFERENCE`, `DIRTY`, `FUSED`):

```text
==================================================
=== ETAP 5G.3 FINAL 5-RUN CANONICAL REBASELINE ===
==================================================
TRUE FPS:           37.902 fps (mediana 37.913, min 37.738, max 38.052, CV 0.36%)
RENDER FPS:         40.361 fps (mediana 40.361)
USER EFFECTIVE FPS: 37.945 fps (mediana 37.945)

Video Render Wall:  28.022 s
Mux Wall:            0.824 s
Total Export Wall:  29.840 s   (mediana 29.832 s)

Producer Prepare:   13.966 ms/frame (mediana 13.669 ms)
Above Total:        10.481 ms/frame (mediana 10.245 ms)
Above Compose:       9.017 ms/frame (mediana  8.832 ms)
Map CPU Upload:      1.022 ms/frame (mediana  1.012 ms)
Gauge Upload:        0.158 ms/frame (mediana  0.156 ms)
Consumer Native:     6.304 ms/frame (mediana  6.551 ms)
VP Submit (CPU):     0.258 ms/frame (mediana  0.257 ms)
AMF Submit:          0.442 ms/frame (mediana  0.376 ms)
AMF Query:           0.161 ms/frame (mediana  0.149 ms)
==================================================
```

---

## 4. Fresh Component-Level Bottleneck Ranking (ETAP F)

Profilowanie 1131 klatek 4K wszystkich aktywnych komponentów warstwy CPU:

| Ranga | Komponent / Widget | Czas średni (ms) | Mediana (ms) | P95 (ms) | Rola architektoniczna |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **—** | `above_compose` (Suma CPU ABOVE) | **9.017 ms** | **8.832 ms** | **13.175 ms** | Rysowanie widgetów tekstowych na płótnie Pillow |
| **—** | `above_region_to_bytes` | **1.381 ms** | **1.277 ms** | **2.190 ms** | Konwersja dirty-region do bufora bajtów |
| **—** | `map_cpu_upload` | **1.022 ms** | **1.012 ms** | **1.678 ms** | Przygotowanie kafelka mapy dynamicznej dla GPU |
| **—** | `above_exact_crop` | **0.934 ms** | **0.852 ms** | **1.543 ms** | Kadrowanie zmienionego obszaru dirty rect |
| **—** | `above_tight_bbox_collect` | **0.594 ms** | **0.589 ms** | **1.131 ms** | Zbieranie bounding boxów wklejonych widgetów |
| **1** | `compass` (render widgetu) | **0.182 ms** | **0.021 ms** | **0.533 ms** | Render igły i tarczy kompasu |
| **2** | `time_display` (render widgetu) | **0.090 ms** | **0.078 ms** | **0.144 ms** | Render czasu i daty |
| **3** | `slope_text` (render widgetu) | **0.026 ms** | **0.013 ms** | **0.024 ms** | Render paska nachylenia |
| **4** | `dist_visual` (render widgetu) | **0.025 ms** | **0.020 ms** | **0.033 ms** | Render paska dystansu |
| **5** | `fit_curVpower_text` | **0.021 ms** | **0.011 ms** | **0.022 ms** | Render mocy |

### Kluczowa obserwacja architektoniczna (True Critical Path):
- Wskaźniki dynamiczne (kompas, nachylenie, moc, dystans, czas) kosztują łącznie zaledwie **~0.4 ms** na klatkę dzięki zoptymalizowanym cache'om `_BoundedStaticCache`.
- Główny koszt CPU (`above_compose` ~9.0 ms oraz `above_exact_crop` + `above_region_to_bytes` ~2.3 ms) wynika z **rysowania i kadrowania dirty-region na pełnym płótnie 4K (3840x2160)** w Pillow.
- W szczególności zbieranie i ekstrakcja exact crop (`above_exact_crop` + `above_tight_bbox_collect` + `above_region_to_bytes` = **2.91 ms**) stanowi bezpośredni narzut transferu dirty-rect CPU→GPU.
