# RAPORT AMD — ETAP 5Q: redukcja CPU hotspotów compose_overlay (max 2) + pomiar absorpcji przez pacing

**STATUS: ✅ PASS-LOCAL-NO-WALL-GAIN** — obie optymalizacje **pixel-exact**
(1131 klatek, MAE=0/MAX=0, framemd5 identyczny), compose_overlay **−3.2 ms/klatkę
(−39 %)** w production, ale zysk wall-clock jest marginalny (w szumie):
**native pacing `process_frame` wchłonął 280.9 %** uwolnionego CPU (jak w 5N/5P).
Bez zmian AMF / telemetry / GPU map / chart / gauge compositing pipeline; **bez 5R**.
Brak przebudowy DLL (tylko Python) — zgodnie ze spec (g++.exe nadal zablokowany).

---

## CONTROL / METODY

| Run | tryb | wall [s] | TRUE FPS | valid |
|---|---|---|---|---|
| **A** | production REFERENCE (acct OFF) | 45.51 | 27.04 | ✅ |
| **B** | production OPTIMIZED (acct OFF) | 36.81 | 32.42 | ✅ |
| **C** | production REFERENCE (acct OFF) | 34.75 | 34.36 | ✅ |
| **D** | production OPTIMIZED (acct OFF) | 37.65 | 31.61 | ✅ |
| **E** | accounting ON + REFERENCE | 37.54 | 31.69 | ✅ |
| **F** | accounting ON + OPTIMIZED | 37.71 | 31.47 | ✅ |

Wszystkie runy: pełna architektura produkcyjna (D3D11VA → GPU_HUD → GPU_SPLIT
charts → GPU gauge → GPU map LANCZOS → AMF HEVC CQP28), telemetry REFERENCE,
1131 klatek, drops=0, cadence/hr/map/gauge GPU = 1131. Tryb wybierany flagą
**`AMD_COMPOSE_5Q=REFERENCE|OPTIMIZED`** (domyślnie REFERENCE).

---

## PROFILE BEFORE (compose, 400 klatek, mediana per-widget)

| widget | total [ms] | najdroższa składowa |
|---|---|---|
| **gauge** (fit_enhanced_speed_text) | **2.392** | text drawing 1.207 · copy 0.640 · textbbox 0.271 |
| **cadence** (fit_cadence_text) | **1.885** | background_and_chart_composite 1.675 · dynamic_labels 1.267 |
| iso | 1.499 | text drawing 0.988 (65% unikalnych — nie cache'owalne) |
| **HR** (fit_heart_rate_text) | **1.332** | dynamic_labels 0.947 |
| time_block | 1.233 | paste_composite 1.108 (_clean_transparency ~0.5 ms — 3. kandydat, odrzucony: spec max 2) |

Globalne ops: text drawing 4.136 · background_composite 2.946 · dynamic_labels 2.257.

---

## SELECTED HOTSPOT 1 — gauge center text tile cache (`src/indicators/gauge.py`)

- **Koszt przed**: `draw.text` + `textbbox` ze stroke ~**1.5 ms/klatkę** na 648×648 gauge.
- **Hit-rate (POMIAR)**: config gauge ma `decimals:2` → `txt_main` = `"10.00 km/h"` →
  **639 unikalnych stringów / 1131 klatek → 43.5 % hit** (to NIE 2.5 % — 2.5 % to
  hit-rate surowego floata `value`, nie sformatowanego tekstu).
- **Implementacja**: cache w `_STATIC_CACHE` keyed
  `("gauge_value_text", txt_main, _c_font, text_color, outline)`; przy trafieniu
  `alpha_composite(cached_tile, (px+sl, py+st))` zamiast `textbbox`+`draw.text`.
  Tile renderowany na `(-sl, -st)` (stroke-inclusive bbox) — reprodukuje dokładnie
  piksele direct draw (src-over).
- **Zapis**: ~0.6 ms/klatkę netto (hity pomijają textbbox+draw.text; missy ~+0.05 ms za composit).

## SELECTED HOTSPOT 2 — chart dynamic value tile cache (`src/indicators/chart.py`)

- **Koszt przed**: `_render_value_text_tile` (value label w GPU_SPLIT) —
  **cadence 1.267 ms + HR 0.947 ms** = ~2.2 ms/klatkę.
- **Hit-rate (POMIAR)**: cadence 11 unikalnych wartości (98.7 % powtórzeń),
  HR 12 (98.3 %) → **~98 % hit**.
- **Implementacja**: cache w `_STATIC_CACHE` keyed
  `("value_text_tile", v_str, font.path, font.size, text_color, outline)` przechowujący
  `(tile, vw, sl, st)`; przy trafieniu pozycje `(px,py)` przeliczane tanio z
  zcache'owanych metryk (bez textbbox). Tile bajt-identyczny (te same argumenty draw).
- **Zapis**: ~2.1 ms/klatkę (cadence + HR).

> Oba cache'e dzielą istniejący wzorzec `_STATIC_CACHE`/`_static_cache_key`
> (używany już przez gauge_bg / chart_hdr / time_block / iso). Zgodnie ze spec
> **max 2** optymalizacje — odrzucony 3. kandydat (`_clean_transparency` cache
> w rotated_paste, ~0.5 ms time_block), choć byte-exact.

---

## CORRECTNESS (spec sekcja 10/11)

### Byte-exact gate (scratch/etap5q_exactness.py) — 1131 klatek, oba tryby w 1 procesie

| artefakt | MAE | MAX | bad_frames | mismatch_px |
|---|---|---|---|---|
| hud_full (CPU, wszystkie widgety) | 0.0 | 0 | 0 | 0 |
| hud_split (GPU_SPLIT, nie-capture) | 0.0 | 0 | 0 | 0 |
| gauge (captured 648×648) | 0.0 | 0 | 0 | 0 |
| chart cadence: static / cursor / value / value_local | 0.0 | 0 | 0 | 0 |
| chart HR: static / cursor / value / value_local | 0.0 | 0 | 0 | 0 |
| **mismatching frames (any)** | | | **0 / 1131** | |

> Ważne: w GPU capture widgety chart/gauge NIE są wklejane do pełnego HUD
> (idą do `gpu_capture`) — gate porównywał więc osobno pełny HUD CPU **i**
> przechwycone tile (gauge image, value/cursor/static chart tiles). Wszystkie
> **MAE=0 / MAX=0 / 0 mismatching frames**.
> Sanity: gałąź OPT faktycznie się wykonała (cache entries: gauge_value_text=639,
> value_text_tile=23).

### framemd5 pełnego pipeline (spec sekcja 11)

- Short 31 klatek OPTIMIZED vs REFERENCE (pełna architektura D3D11VA→GPU→AMF):
  **31/31 klatek, 0 rozbieżnych hashy** — wyjście video bajt-identyczne.

---

## MICROBENCH (spec sekcja 13) — scratch/etap5q_microbench.py

5 zimnych przebiegów × 1131 klatek, konfiguracja produkcyjna GPU_SPLIT capture.

| | median [ms] | p95 [ms] | p99 [ms] | avg [ms] |
|---|---|---|---|---|
| REFERENCE | 21.760 | 29.228 | 40.229 | 22.751 |
| OPTIMIZED | 20.520 | 27.545 | 41.029 | 21.533 |
| **saving** | **−1.240 (−5.7 %)** | −1.683 | +0.800 | −1.218 |

> Mikrobench mierzy z profilerem overlay ON (narzut obu trybów); realny zapis
> w production (profil OFF) jest większy — patrz A/B/C/D (compose −3.2 ms).

---

## SHORT 31 — pełna architektura (spec sekcja 15)

`AMD_COMPOSE_5Q=OPTIMIZED` + GPU map LANCZOS + GPU_SPLIT + GPU gauge + REFERENCE telemetry:
D3D11VA YES, P010, 31/31 klatek, AMF 31/31, drops=0, compose med **9.07 ms**,
framemd5 ≡ REFERENCE. Wizualnie OK (bez ghost/green/black).

---

## PRODUCTION A/B/C/D (spec sekcja 17, accounting OFF)

| Run | tryb | TRUE FPS | compose med [ms] | wall [s] |
|---|---|---|---|---|
| A | REFERENCE | 27.04 | 6.592 | 45.51 |
| B | OPTIMIZED | 32.42 | 4.818 | 36.81 |
| C | REFERENCE | 34.36 | 9.314 | 34.75 |
| D | OPTIMIZED | 31.61 | 4.658 | 37.65 |
| **REF med** | | **30.70** | **7.953** | **40.13** |
| **OPT med** | | **32.02** | **4.738** | **37.23** |
| **delta** | | **+1.32 (+4.29 %)** | **−3.215 (−40.4 %)** | **−2.90 s (−7.2 %)** |

> Zastrzeżenie: run A (pierwszy, zimny GPU/CPU boost) jest anomalnie wolny
> (27.04 FPS); porównanie par B(OPT 32.4) vs C(REF 34.4) i D(OPT 31.6) vs C(REF 34.4)
> pokazuje, że OPT **nie** jest stabilnie szybszy wall od REF w sąsiednich runach.
> **Compose med jest natomiast konsekwentnie ~3.2 ms szybszy w OPT (4.74 vs 7.95).**
> Zysk wall w A/B/C/D jest w dużej mierze artefaktem zimnego runu A.

---

## ACCOUNTING E/F + GAIN ABSORPTION (spec sekcja 18/19)

| stage | E (REF) [ms] | F (OPT) [ms] | delta |
|---|---|---|---|
| **compose** | 8.215 | 4.985 | **−3.229** |
| **process_frame** (native pacing) | 4.048 | **13.120** | **+9.072** |
| telemetry | 4.285 | 3.058 | −1.227 |
| map_upload | 2.074 | 2.196 | +0.121 |
| gauge_upload | 1.397 | 1.444 | +0.046 |
| hud_dirty | 0.828 | 0.922 | +0.094 |
| **frame_total med** | **29.343** | **28.094** | **−1.248** |
| TRUE FPS | 31.69 | 31.47 | −0.22 |

```
compose_saved      = 8.215 − 4.985 = 3.229 ms
process_frame_shift = 13.120 − 4.048 = +9.072 ms
frame_saved         = 29.343 − 28.094 = 1.248 ms
absorbed by pacing  = process_frame_shift / compose_saved = 280.9 %
```

> **Absorpcja 280.9 %** — native `process_frame` (elastyczne pacing GPU/AMF)
> **wchłonął CAŁĄ oszczędność compose i więcej** (+9.07 ms przy uwolnionych 3.23 ms).
> frame_total poprawił się tylko o **1.25 ms (−4.3 %)**, a TRUE FPS w E/F jest
> równy w szumie (31.69 → 31.47). To ten sam mechanizm co w 5N (telemetry 200×
> szybsze, wall bez zmian) — pipeline jest zablokowany na cadence GPU/AMF
> (~30 FPS), a uwolniony CPU jest przekładany na dłuższy wait w `process_frame`.

---

## BOTTLENECKS AFTER 5Q

1. **Native pacing `process_frame`** (13.1 ms w OPT vs 4.0 ms w REF) — elastyczny
   limiter; wchłania każdą oszczędność CPU. Nie CPU-bound w klasycznym sensie —
   to synchronizacja z GPU/AMF cadence.
2. **telemetry** (3.1–4.3 ms REFERENCE) — nadal ~3–4 ms na klatkę (cache 5N
   niedostępny bez PRECOMPUTED; nie używany w 5Q zgodnie ze spec).
3. **map_upload** (~2.1–2.2 ms CPU).
4. **gauge_upload** (~1.4 ms).
5. **hud_dirty** (~0.9 ms).
6. compose_overlay **spadł z ~8–9 ms do ~4.7–5.0 ms** (już nie jest największym
   stage CPU w OPT; nadal istotny w REF).

> Wniosek: compose NIE był limiterem wall — był drugim co do wielkości stage CPU,
> ale pipeline jest GPU/AMF-pacing-bound. Redukcja compose jest realna, pixel-exact
> i pożądana (niższe zużycie CPU, zapas na inne obciążenia), ale **nie przekłada
> się na wall-clock** dopóki limiterem jest native pacing/cadence AMF.

---

## ODPOWIEDZ WPROST

1. **Które 2 hotspoty compose wybrano?** → **(1) gauge center text** (draw.text+textbbox ~1.5 ms,
   hit 43.5 %) oraz **(2) chart dynamic value label** (`_render_value_text_tile`, cadence 1.27 ms
   + HR 0.95 ms, hit ~98 %). Razem docelowo ~2.8 ms/klatkę lokalnie.
2. **Czy optymalizacje są pixel-exact?** → **TAK** — 1131 klatek, MAE=0/MAX=0,
   0 mismatching frames na wszystkich artefaktach (full HUD + capture tiles);
   **framemd5 31/31 identyczny** w pełnym pipeline.
3. **Ile zapisano na compose?** → production: **−3.23 ms/klatkę (−39 %)**
   (accounting E/F: 8.215→4.985); A/B/C/D compose med 7.95→4.74 (−40.4 %).
4. **Ile zapisano w mikrobenchu?** → **−1.24 ms (−5.7 %)** median (REF 21.76→OPT 20.52)
   z profilerem ON; bez profilerem zapis większy (patrz production).
5. **Jaki jest realny zysk frame_total/wall?** → frame_total med **−1.25 ms (−4.3 %)**
   w E/F; TRUE FPS w szumie (A/B/C/D med +4.29 % — zafałszowane zimnym runem A;
   E/F 31.69→31.47 −0.7 %). **Brak stabilnego zysku wall-clock.**
6. **Ile procent oszczędności CPU zostało wchłonięte przez pacing?** →
   **280.9 %** — `process_frame` wzrósł o 9.07 ms (4.05→13.12) przy uwolnionych
   3.23 ms z compose; frame_total zyskał tylko 1.25 ms.
7. **Klasyfikacja ETAPU 5Q?** → **PASS-LOCAL-NO-WALL-GAIN** (pixel-exact + compose
   lokalnie szybszy, ale pacing wchłania zysk — jak 5N).
8. **Czy kompozycja GPU (map/chart/gauge) została zmieniona?** → **NIE** — renderery
   GPU capture bez zmian; dotknięte tylko: render `_render_gauge_indicator`
   (cache tekstu), `_render_value_text_tile` (cache tile), `helpers.compose_5q_optimized`.
9. **Czy TeleM przekracza realtime 29.97 FPS?** → **NIE stabilnie** — mediana
   A/B/C/D to 30.70 REF / 32.02 OPT (tylko mediana OPT lekko powyżej; pojedyncze runy
   31.5–34.4), ale wariancja termiczna > sygnał; E/F 31.5–31.7. Brak gwarantowanego
   przekroczenia realtime.
10. **Czy wymagano przebudowy DLL / zmian native?** → **NIE** — wyłącznie Python
    (g++.exe nadal zablokowany polityką Windows); ABI 8 bez zmian.
11. **Jaki jest największy bottleneck po 5Q?** → **Native pacing `process_frame`
    (synchronizacja GPU/AMF cadence ~30 FPS)** — nie compose; następnie telemetry
    (~3–4 ms) i map/gauge upload.
12. **Czy wykonano ETAP 5R?** → **NIE** — zgodnie ze spec nie wykonywano 5R.

---

## KRYTERIA PASS (spec sekcja 20)

| # | kryterium | wynik |
|---|---|---|
| 1 | max 2 optymalizacje compose | ✅ (dokładnie 2) |
| 2 | pixel-exact (1131 klatek, MAE=0/MAX=0) | ✅ (0 mismatching frames) |
| 3 | framemd5 REF ≡ OPT | ✅ (31/31 short; kompozytowo 1131 gate) |
| 4 | mikrobench REF vs OPT (5×1131) | ✅ (−1.24 ms, −5.7 %) |
| 5 | production A/B/C/D 1131 | ✅ (4 runy, valid; compose −3.2 ms) |
| 6 | accounting E/F + absorpcja | ✅ (280.9 % wchłonięte przez pacing) |
| 7 | klasyfikacja | **PASS-LOCAL-NO-WALL-GAIN** |
| 8 | bez zmian AMF / telemetry / GPU compositing | ✅ |
| 9 | bez 5R / bez przebudowy DLL | ✅ |

---

## PLIKI

- Kod: `src/indicators/helpers.py` (`compose_5q_optimized`), `src/indicators/gauge.py`
  (OPT 1), `src/indicators/chart.py` (OPT 2).
- Harnessy: `scratch/etap5q_exactness.py`, `scratch/etap5q_microbench.py`,
  `scratch/etap5q_ab.py`, `scratch/etap5q_accounting.py`, `scratch/etap5q_compose_profile.py`.
- JSON: `Raporty/AMD_ETAP5G/etap5q_ab.json`, `etap5q_accounting.json`,
  `etap5q_microbench_reference.json`, `etap5q_microbench_optimized.json`,
  `l5q_profile.mp4.amd_profile.json`.
- Wyjścia: `Raporty/AMD_ETAP5G/l5q_A/B/C/D/E/F.mp4`, `l5q_short31.mp4`, `l5q_short31_ref.mp4`.
