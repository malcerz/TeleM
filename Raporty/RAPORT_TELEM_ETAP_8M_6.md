# RAPORT: TeleM — ETAP 8M.6: Naprawa Clippingu Etykiet i Wartości Osi Wykresów

**Data wykonania:** 2026-08-19  
**Status etapu:** ZAKOŃCZONY SUKCESEM (Pełna widoczność etykiet osi X i Y, brak clippingu `0%` i `100%`, poprawny kontrakt padding/margins dla Preview i AMD GPU Final)  
**Cel etapu:** Identyfikacja i eliminacja przyczyny obcinania skrajnych etykiet osi X (`100%` oraz `%`) i osi Y (`Y-max`), zachowanie integralności geometrii opartej na znacznikach czasu (ETAP 8M.4), zapewnienie 100% parytetu podglądu (Preview) i eksportu sprzętowego (AMD D3D11+AMF) bez optymalizacji wydajnościowych.

---

## A. Exact Clipping Root Cause

Pomiar geometrii wskaźników `fit_cadence_text` oraz `fit_heart_rate_text` przed poprawką:
- Obraz tła wykresu (`bg_img`) ma szerokość `chart_w` (np. $576\text{ px}$ w $1080\text{p}$).
- W funkcji `_build_chart_bg` prawy margines osi był na sztywno zdefiniowany jako `axis_right_margin = 4 * ss` ($4\text{ px}$).
- Prawa granica obszaru rysowania serii danych wynosiła:
  $$plot\_x2 = width - axis\_right\_margin = 576 - 4 = 572\text{ px}$$
- Etykieta `100%` (lub dowolna ostatnia etykieta osi X) jest centrowana względem $x = plot\_x2 = 572\text{ px}$.
- Szerokość tekstu `100%` wynosi $tw = 25\text{ px}$ (lub więcej przy większych czcionkach/outline).
- Pozycja tekstu wynosiła:
  $$tx = plot\_x2 - \lfloor tw / 2 \rfloor = 572 - 12 = 560\text{ px}$$
  $$text\_right = tx + tw = 560 + 25 = 585\text{ px}$$
- Ponieważ granica płótna `bg_img` kończy się na $x = 576\text{ px}$, piksele w przedziale $x \in (576 \dots 585]$ ($9\text{ px}$) były **obcinane przez Pillow/rasterizer**, co powodowało ucięcie znaku `%` oraz części zera.

---

## B. Chart Canvas vs Plot Geometry

Rozróżnienie obszarów i współrzędnych:
1. **Widget Canvas (`final_img` / `final_static`)**: Szerokość $chart\_w + 8$, Wysokość $final\_h = chart\_h + margin\_top + 4$.
2. **Chart BG Canvas (`bg_img`)**: Szerokość $chart\_w$, Wysokość $chart\_h$.
3. **Plot Area (`[plot_x1 .. plot_x2] x [plot_y1 .. plot_y2]`)**:
   - `plot_x1`: początek zakresu serii danych ($t_{\text{start}}$ / $0\%$).
   - `plot_x2`: koniec zakresu serii danych ($t_{\text{end}}$ / $100\%$).
   - `plot_w = plot_x2 - plot_x1`: logiczna i fizyczna szerokość wykresu.
   - Odwzorowanie czasu: $x = plot\_x1 + \frac{t - t_{\text{start}}}{t_{\text{end}} - t_{\text{start}}} \cdot plot\_w$.
   
Model paddingu gwarantuje, że obszar danych rozciąga się w $100\%$ między $plot\_x1$ a $plot\_x2$, a etykiety tekstowe mieszczą się w buforze `bg_img` dzięki dynamicznym marginesom.

```text
widget canvas (chart_w + 8)
┌────────────────────────────────────────────────────────┐
│ Title / Label                          Current Value   │
│ ┌────────────────────────────────────────────────────┐ │
│ │ L-margin                Plot Area         R-margin │ │
│ │ (Y-labels)   |-------------------------|   (100%)  │ │
│ │ 87           |                         |           │ │
│ │ 0            |_________________________|           │ │
│ │             0%   25%   50%   75%    100%           │ │
│ └────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

---

## C. Text BBox Analysis

Dla rozdzielczości $1920 \times 1080$ ($chart\_w = 576\text{ px}$, $chart\_h = 230\text{ px}$):

| Element | Tekst | BBox $(w \times h)$ | Anchor $(x, y)$ | Pozycja w buforze | Status po poprawce |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **X Label 0%** | `0%` | $13 \times 8$ | $(28.0, 184.0)$ | $[22.0 \dots 35.0]$ | **UNCLIPPED** (Left margin: $22\text{ px} \ge 0$) |
| **X Label 25%** | `25%` | $19 \times 8$ | $(160.8, 184.0)$ | $[151.8 \dots 170.8]$| **UNCLIPPED** |
| **X Label 50%** | `50%` | $19 \times 8$ | $(293.5, 184.0)$ | $[284.5 \dots 303.5]$| **UNCLIPPED** |
| **X Label 75%** | `75%` | $19 \times 8$ | $(426.2, 184.0)$ | $[417.2 \dots 436.2]$| **UNCLIPPED** |
| **X Label 100%** | `100%` | $25 \times 8$ | $(559.0, 184.0)$ | $[547.0 \dots 572.0]$| **UNCLIPPED** (Right margin: $4\text{ px} \le 576$) |
| **Y Label Min** | `77` | $13 \times 8$ | $(28.0, 184.0)$ | $y \in [182.0 \dots 190.0]$ | **UNCLIPPED** |
| **Y Label Max** | `116` | $19 \times 8$ | $(28.0, 4.0)$ | $y \in [2.0 \dots 10.0]$ | **UNCLIPPED** ($y \ge 0$) |
| **Title** | `Heart Rate` | $112 \times 19$ | $(4, 0)$ | $[4 \dots 116]$ | **UNCLIPPED** |
| **Current Value**| `100 BPM` | $98 \times 19$ | $(478, 0)$ | $[478 \dots 576]$ | **UNCLIPPED** |

---

## D. Left / Right Padding

W `src/indicators/chart_utils.py` wprowadzono dynamiczne wyliczanie marginesów poziomych:
- `left_x_label = x_labels[0]` (domyślnie `"0%"`)
- `right_x_label = x_labels[-1]` (domyślnie `"100%"`)
- `left_hw = textbbox(left_x_label).width / 2.0`
- `right_hw = textbbox(right_x_label).width / 2.0`
- `axis_left_margin = int(math.ceil(max(max_label_w + 10 * ss, left_hw + 4 * ss)))`
- `axis_right_margin = int(math.ceil(right_hw + 4 * ss))`

Dzięki temu prawy margines `axis_right_margin` wynosi dokładnie tyle, ile wynosi połowa szerokości tekstu `100%` powiększona o margines bezpieczeństwa ($4\text{ px}$).

---

## E. Top / Bottom Padding

- `axis_top_margin = int(math.ceil(max(4 * ss, max_label_h / 2.0)))`: zapewnia, że górna etykieta osi Y (np. $116$) centrowana względem $plot\_y1$ nie wychodzi poza górną krawędź bufora ($y \ge 0$).
- `axis_bottom_margin = int(max(6, height * 0.20)) * ss`: zapewnia wystarczającą przestrzeń ($20\%$ wysokości wykresu) na etykiety osi X i podziałki.

---

## F. Static GPU Chart Texture

W potoku AMD Native (`GPU_SPLIT`):
- Tekstura statyczna (`final_static`) ma wymiary $(chart\_w + 8) \times final\_h$.
- Całość tła (`bg_img`) wraz z etykietami osi X (`0% .. 100%`), osi Y oraz tytułem jest wklejana na pozycję $(4, margin\_top)$.
- Zewnętrzny bounding box wskaźnika nie uległ zmianie (ten sam widget bbox w layoutcie).

---

## G. Dynamic Cursor / Value Tiles

- Kursor (`_cursor_tile_bbox` oraz `_draw_post_paste_cursor`) pobiera punkty wyliczone z nowych współrzędnych $plot\_x1 \dots plot\_x2$ oraz $plot\_y1 \dots plot\_y2$.
- Płytka wartości bieżącej (`_render_value_text_tile`) jest poprawnie przycinana funkcją `_clip_tile` do rozmiaru $(chart\_w + 8) \times final\_h$.

---

## H. Cadence Before / After

| Cecha | Przed poprawką (Before) | Po poprawce (After) |
| :--- | :--- | :--- |
| **Etykieta 100%** | Ucięty znak `%` i prawe zero | **W 100% widoczne `100%` z marginesem 4px** |
| **Etykieta 0%** | Widoczna | **Widoczna** |
| **Y Min / Max (0 / 87)** | Widoczne | **Widoczne** |
| **BBox wideo** | $(960, 804, 584, 261)$ | $(960, 804, 584, 261)$ |

---

## I. Heart Rate Before / After

| Cecha | Przed poprawką (Before) | Po poprawce (After) |
| :--- | :--- | :--- |
| **Etykieta 100%** | Ucięty znak `%` i prawe zero | **W 100% widoczne `100%` z marginesem 4px** |
| **Etykieta 0%** | Widoczna | **Widoczna** |
| **Y Min / Max (77 / 116)** | Widoczne | **Widoczne** |
| **BBox wideo** | $(1260, 804, 584, 261)$ | $(1260, 804, 584, 261)$ |

---

## J. Activity Scope

Dla `chart_time_scope = "activity"`:
- Pełna aktywność FIT (1704 punkty) odwzorowywana jest w $100\%$ między $plot\_x1$ a $plot\_x2$.
- Kursor bieżącego czasu wideo porusza się w proporcjonalnym wycinku aktywności.
- Skrajne etykiety $0\%$ i $100\%$ są całkowicie nieobcięte.

---

## K. Video Scope

Dla `chart_time_scope = "video"`:
- Zakres wykresu obejmuje czas filmu ($0.00\text{ s} \dots 37.74\text{ s}$).
- Etykiety $0\%$ i $100\%$ zachowują tę samą nieobciętą geometrię.

---

## L. Preview / Final Parity

Wszystkie etapy potoku (Preview, CPU, GPU static, GPU dynamic, Final AMD MP4) wykazują $100\%$ zgodność pozycji i widoczności etykiet.
Artefakty zapisane w `Raporty/etap8m6_artifacts/`:
- `01_preview_chart_cad.png` & `02_preview_chart_hr.png`
- `03_cpu_chart_cad.png` & `04_cpu_chart_hr.png`
- `05_gpu_static_chart_cad.png` & `06_gpu_static_chart_hr.png`
- `07_final_chart_cad.png` & `08_final_chart_hr.png`
- `cad_preview.png`, `cad_final.png`, `hr_preview.png`, `hr_final.png`

---

## M. Multi-Resolution Validation

| Rozdzielczość | Chart Canvas | Etykieta 100% Text Right | Margines prawy | Status |
| :--- | :--- | :--- | :--- | :--- |
| **4K** ($3840 \times 2160$) | $1152 \times 460$ | $1148.0\text{ px}$ | $+4.0\text{ px}$ | **PASS** |
| **1080p** ($1920 \times 1080$) | $576 \times 230$ | $572.0\text{ px}$ | $+4.0\text{ px}$ | **PASS** |
| **720p** ($1280 \times 720$) | $384 \times 153$ | $380.0\text{ px}$ | $+4.0\text{ px}$ | **PASS** |
| **480p** ($854 \times 480$) | $256 \times 102$ | $252.0\text{ px}$ | $+4.0\text{ px}$ | **PASS** |

---

## N. Tests

Utworzono zestaw testów `tests/test_etap8m6_chart_labels.py` (10/10 PASSED):
1. `test_chart_right_100_percent_not_clipped` — weryfikacja braku clippingu etykiety `100%`.
2. `test_chart_left_0_percent_not_clipped` — weryfikacja lewego marginesu etykiety `0%`.
3. `test_chart_y_min_not_clipped` — weryfikacja dolnej etykiety osi Y.
4. `test_chart_y_max_not_clipped` — weryfikacja górnej etykiety osi Y ($y \ge 0$).
5. `test_chart_labels_include_outline_in_bbox` — weryfikacja kompletności obrysu i bounding boxa.
6. `test_chart_static_texture_contains_all_labels` — weryfikacja statycznej tekstury GPU.
7. `test_chart_activity_scope_label_geometry` — weryfikacja geometrii w trybie `activity`.
8. `test_chart_video_scope_label_geometry` — weryfikacja geometrii w trybie `video`.
9. `test_chart_preview_final_label_parity` — weryfikacja parytetu Preview i CPU.
10. `test_chart_labels_multi_resolution` — weryfikacja braku clippingu w 4K, 1080p, 720p i 480p.

---

## O. Full Suite Status

- **Passed**: 383 testy (wzrost z 373 po dodaniu 10 testów etapu 8M.6)
- **Failed**: 3 testy (znane, pre-istniejące asercje ABI/mocków niepowiązane z wskaźnikami)
- **Skipped**: 17 testów

---

## P. Final Classification

| Kryterium | Status |
| :--- | :--- |
| **X LABEL 0%** | **PASS** |
| **X LABEL 100%** | **PASS** |
| **Y MIN/MAX** | **PASS** |
| **CURRENT VALUE** | **PASS** |
| **ACTIVITY SCOPE** | **PASS** |
| **VIDEO SCOPE** | **PASS** |
| **PREVIEW/FINAL PARITY** | **PASS** |
| **MULTI-RES CHART LABELS** | **PASS** |
