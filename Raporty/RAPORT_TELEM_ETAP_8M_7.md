# RAPORT TELEM — ETAP 8M.7: Naprawa clippingu całego Chart Widget przy krawędzi finalnej klatki

## A. Why 8M.6 produced false real-world PASS
W etapie 8M.6 naprawiono wewnętrzny clipping etykiet w obrębie lokalnego canvasu wykresu (`_build_chart_bg` w `chart_utils.py`), wprowadzając dynamiczne marginesy dla etykiet osi X i Y.
Jednakże test jednostkowy 8M.6 weryfikował wyłącznie to, czy etykiety mieszczą się **wewnątrz lokalnej tekstury wykresu** (`text bbox <= local chart canvas`). 
W rzeczywistym renderingu pełnoklatkowym (GUI Preview oraz AMD GPU final export):
1. Wykres jako cały widget ma rozmiar zewnętrzny `(chart_w + 8) x (chart_h + margin_top + 4)`.
2. Umieszczany jest na klatce wideo według punktu centralnego `(center_x, center_y)`.
3. Przy domyślnym lub zbliżonym do dolnej krawędzi położeniu `y` (np. $85.36\%$, $90.0\%$, $95.0\%$) w niskich rozdzielczościach (720p, 480p) lub przy skrajnym pozycjonowaniu, brak walidacji i dopasowania zewnętrznej geometrii wykresu powodował, że dolna krawędź widgetu z etykietami $0\% \dots 100\%$ przekraczała dolną granicę klatki wideo (`final_bottom > canvas_height`).

---

## B. Logical widget bbox
Wynikający z konfiguracji `def_layout.json` (dla rozdzielczości referencyjnych):
- **Cadence (`fit_cadence_text`):** $x = 19.93\%$, $y = 85.36\%$, $\text{size} = 30.0\%$
  - 4K ($3840 \times 2160$): $rx = 765\text{ px}$, $ry = 1844\text{ px}$, $\text{size\_px} = 1152\text{ px}$
  - 1080p ($1920 \times 1080$): $rx = 383\text{ px}$, $ry = 922\text{ px}$, $\text{size\_px} = 576\text{ px}$
  - 720p ($1280 \times 720$): $rx = 255\text{ px}$, $ry = 615\text{ px}$, $\text{size\_px} = 384\text{ px}$
  - 480p ($854 \times 480$): $rx = 170\text{ px}$, $ry = 410\text{ px}$, $\text{size\_px} = 256\text{ px}$
- **Heart Rate (`fit_heart_rate_text`):** $x = 79.61\%$, $y = 85.50\%$, $\text{size} = 30.0\%$
  - 4K ($3840 \times 2160$): $rx = 3057\text{ px}$, $ry = 1847\text{ px}$, $\text{size\_px} = 1152\text{ px}$
  - 1080p ($1920 \times 1080$): $rx = 1529\text{ px}$, $ry = 923\text{ px}$, $\text{size\_px} = 576\text{ px}$
  - 720p ($1280 \times 720$): $rx = 1019\text{ px}$, $ry = 616\text{ px}$, $\text{size\_px} = 384\text{ px}$
  - 480p ($854 \times 480$): $rx = 680\text{ px}$, $ry = 410\text{ px}$, $\text{size\_px} = 256\text{ px}$

---

## C. Local render bbox
Rzeczywisty rozmiar rastra `final_static` / `final_img` (`width x height`):
- **4K:** $1160 \times 511\text{ px}$ ($\text{chart\_w}=1152$, $\text{chart\_h}=460$, $\text{margin\_top}=47$, $+4\text{ pad}$)
- **1080p:** $584 \times 261\text{ px}$ ($\text{chart\_w}=576$, $\text{chart\_h}=230$, $\text{margin\_top}=27$, $+4\text{ pad}$)
- **720p:** $392 \times 178\text{ px}$ ($\text{chart\_w}=384$, $\text{chart\_h}=153$, $\text{margin\_top}=21$, $+4\text{ pad}$)
- **480p:** $264 \times 123\text{ px}$ ($\text{chart\_w}=256$, $\text{chart\_h}=102$, $\text{margin\_top}=17$, $+4\text{ pad}$)

---

## D. Final visual bbox
Lokalny raster umieszczony na docelowej klatce wideo (`left, top, right, bottom`):

| Rozdzielczość | Wskaźnik | Final Visual BBox (`L, T, R, B`) | Canvas Height | Margin do dolnej krawędzi | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **4K** | Cadence | $(185, 1588, 1345, 2099)$ | $2160\text{ px}$ | $+61\text{ px}$ | **PASS** |
| **4K** | Heart Rate | $(2477, 1592, 3637, 2103)$ | $2160\text{ px}$ | $+57\text{ px}$ | **PASS** |
| **1080p** | Cadence | $(91, 792, 675, 1053)$ | $1080\text{ px}$ | $+27\text{ px}$ | **PASS** |
| **1080p** | Heart Rate | $(1237, 792, 1821, 1053)$ | $1080\text{ px}$ | $+27\text{ px}$ | **PASS** |
| **720p** | Cadence | $(59, 526, 451, 704)$ | $720\text{ px}$ | $+16\text{ px}$ | **PASS** |
| **720p** | Heart Rate | $(823, 527, 1215, 705)$ | $720\text{ px}$ | $+15\text{ px}$ | **PASS** |
| **480p** | Cadence | $(38, 348, 302, 471)$ | $480\text{ px}$ | $+9\text{ px}$ | **PASS** |
| **480p** | Heart Rate | $(548, 348, 812, 471)$ | $480\text{ px}$ | $+9\text{ px}$ | **PASS** |

---

## E. Global text bboxes
Współrzędne pionowe etykiet $0\% \dots 100\%$ na finalnej klatce:
- **4K:** `text_top` = $2008\text{ px}$, `text_bottom` = $2050\text{ px}$ (zapas do dołu klatki: **$110\text{ px}$**)
- **1080p:** `text_top` = $1008\text{ px}$, `text_bottom` = $1029\text{ px}$ (zapas do dołu klatki: **$51\text{ px}$**)
- **720p:** `text_top` = $675\text{ px}$, `text_bottom` = $689\text{ px}$ (zapas do dołu klatki: **$31\text{ px}$**)
- **480p:** `text_top` = $453\text{ px}$, `text_bottom` = $463\text{ px}$ (zapas do dołu klatki: **$17\text{ px}$**)

Wszystkie etykiety osi X spełniają warunek $0 \le \text{text\_top} < \text{text\_bottom} \le \text{canvas\_height}$.

---

## F. GPU upload clipping
- GPU split path (`ChartSplit` / `telem_amd_update_chart_static` / `telem_amd_update_chart_dynamic`) otrzymuje spójne współrzędne `(paste_x, paste_y)` oraz dynamiczne kafelki ograniczone do bounds (`_clip_tile`).
- Tekstura statyczna o rozmiarze `final_w x final_h` jest wgrywana w całości i nie podlega ucięciu na poziomie D3D11 VideoProcessor / HLSL blend shader, ponieważ jej współrzędne mieszczą się w całości w canvasie HUD ($3840 \times 2160$, $1280 \times 720$ itd.).

---

## G. Placement/anchor contract
- Format `form="chart"` używa środkowego punktu zaczepienia:
  $$\text{center\_x} = s(\text{cfg}["x"], \text{canvas\_w}), \quad \text{center\_y} = s(\text{cfg}["y"], \text{canvas\_h})$$
  $$\text{paste\_x} = \text{round}(\text{center\_x} - \text{final\_w} / 2), \quad \text{paste\_y} = \text{round}(\text{center\_y} - \text{final\_h} / 2)$$
- Geometry placement contract:
  Dla skrajnych pozycji layoutu (np. $y > 90\%$) rozmiar zewnętrzny wykresu jest ograniczany od wewnątrz poprzez zmniejszenie pola kreślenia (`plot area shrink`), a współrzędne środka są klamrowane (`effective_rx`, `effective_ry`), aby zapobiec wyjściu rastra poza klatkę bez modyfikowania konfiguracji użytkownika w JSON.

---

## H. Exact root cause
1. W `chart_utils.py`, `axis_bottom_margin` był początkowo szacowany stałą estymatą $20\%$, ale nie był dynamicznie powiązany z rzeczywistą wysokością fontu etykiet $0\% \dots 100\%$ (`max_x_label_h`).
2. W `chart.py`, brakowało sprzężenia zwrotnego z rozmiarem klatki (`canvas_h`), co przy wykresach umieszczonych blisko krawędzi powodowało wyjście dolnej krawędzi rastra poza klatkę.

---

## I. Minimal fix
1. **[src/indicators/chart_utils.py](file:///c:/_DEV/TeleM/src/indicators/chart_utils.py):**
   - Dodano dynamiczny pomiar wysokości etykiet osi X (`max_x_label_h`).
   - Wymuszono, aby `axis_bottom_margin >= 5 + max_x_label_h + 2 * ss`, co gwarantuje pełne zmieszczenie etykiet wewnątrz lokalnego tła wykresu.
2. **[src/indicators/chart.py](file:///c:/_DEV/TeleM/src/indicators/chart.py):**
   - Dodano zabezpieczenie wysokości wykresu `max_full_h = 2 * min(_center_y, canvas_h - _center_y)` i redukcję `chart_h` w przypadku zbliżenia do krawędzi ekranu (zasada *plot area shrink*).
   - Wprowadzono wyliczanie `_effective_rx` oraz `_effective_ry`, gwarantujące, że cały raster `final_img` mieści się w granicach $[0, \text{canvas\_w}] \times [0, \text{canvas\_h}]$.

---

## J. 4K ($3840 \times 2160$)
- Visual BBox: $(185, 1588, 1345, 2099)$
- Margines do dolnej krawędzi klatki: **$61\text{ px}$**
- Status: **PASS**

---

## K. 1080p ($1920 \times 1080$)
- Visual BBox: $(91, 792, 675, 1053)$
- Margines do dolnej krawędzi klatki: **$27\text{ px}$**
- Status: **PASS**

---

## L. 720p ($1280 \times 720$)
- Visual BBox: $(59, 526, 451, 704)$
- Margines do dolnej krawędzi klatki: **$16\text{ px}$**
- Margines dolnych etykiet X do krawędzi: **$31\text{ px}$**
- Zapisano pełnoklatkowe zrzuty:
  - `Raporty/etap8m7_artifacts/720p_preview_full.png`
  - `Raporty/etap8m7_artifacts/720p_final_full.png`
- Status: **PASS**

---

## M. 480p ($854 \times 480$)
- Visual BBox: $(38, 348, 302, 471)$
- Margines do dolnej krawędzi klatki: **$9\text{ px}$**
- Margines dolnych etykiet X do krawędzi: **$17\text{ px}$**
- Zapisano pełnoklatkowe zrzuty:
  - `Raporty/etap8m7_artifacts/480p_preview_full.png`
  - `Raporty/etap8m7_artifacts/480p_final_full.png`
- Status: **PASS**

---

## N. Preview/full-frame parity
Pełne klatki podglądu (GUI Preview) wykazują $100\%$ widoczności wszystkich elementów wykresów:
- Tytuł (np. *Cadence*, *Heart Rate*)
- Bieżąca wartość (np. *95.0 rpm*, *145.0 BPM*)
- Oś Y i etykiety min/max
- Oś X i etykiety $0\% \dots 100\%$
- Seria danych, wypełnienie i kursor

---

## O. AMD/full-frame parity
GPU compositing (AMD D3D11 Native / GPU_SPLIT) posiada identyczne umiejscowienie rastra co CPU Preview, a dynamiczne kafelki (kursor, wartość) pokrywają się z warstwą statyczną co do piksela.

---

## P. Tests
Utworzono zestaw 10 testów jednostkowych w [tests/test_etap8m7_chart_frame_clipping.py](file:///c:/_DEV/TeleM/tests/test_etap8m7_chart_frame_clipping.py):
1. `test_chart_visual_bbox_inside_frame_bottom` — **PASSED**
2. `test_chart_bottom_labels_global_bbox` — **PASSED**
3. `test_chart_bottom_edge_no_crop` — **PASSED**
4. `test_chart_static_upload_preserves_bottom_labels` — **PASSED**
5. `test_chart_dynamic_global_coordinates` — **PASSED**
6. `test_chart_outer_geometry_stable_after_padding` — **PASSED**
7. `test_chart_edge_geometry_4k` — **PASSED**
8. `test_chart_edge_geometry_1080p` — **PASSED**
9. `test_chart_edge_geometry_720p` — **PASSED**
10. `test_chart_edge_geometry_480p` — **PASSED**

---

## Q. Full suite
Uruchomienie pełnego zestawu testów repozytorium:
- **Passed:** **393** (wzrost z 383 bazowo po 8M.6 o 10 nowych testów 8M.7)
- **Failed:** **3** (znane, pre-istniejące asercje: `test_amd_native_etap4.py`, `test_qp_analyzer.py`, `test_render_tab.py`)
- **Skipped:** **17**
- **Nowe błędy / regresje:** **0**

---

## R. Final classification

| Kryterium | Status |
| :--- | :--- |
| **INTERNAL LABEL BBOX** | **PASS** |
| **FINAL VISUAL BBOX** | **PASS** |
| **BOTTOM X LABELS** | **PASS** |
| **Y LABELS** | **PASS** |
| **TITLE/CURRENT VALUE** | **PASS** |
| **720P REAL FULL FRAME** | **PASS** |
| **480P REAL FULL FRAME** | **PASS** |
| **PREVIEW/FINAL PARITY** | **PASS** |
