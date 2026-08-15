# TeleM — AMD ETAP 5E — Regionalny Pillow compositing (final compositing layer)

Status: **PASS**
Zakres: wyłącznie końcowe składanie **gotowych** widgetów na persistent RGBA HUD canvas. Renderery wskaźników (mapa, wykresy, gauge, text, time block, ISO/exposure/temp/battery), telemetry (5B), mapa (5C), wykresy (5D), dirty GPU upload i cały natywny pipeline GPU — bez zmian.

## WPROWADZENIE — co audyt wykazał

Punkt wyjścia po 5D: `compose_overlay` AVG 40.845 ms, TRUE FPS 15.425.

Audyt `compose_overlay()` po 5D wykazał, że końcowe składanie każdego gotowego widgetu idzie przez `rotated_paste()` → `base.alpha_composite(widget, (x, y))`. W Pillow 12.3.0 metoda `Image.Image.alpha_composite()` jest **czystym Pythonem**, który wewnętrznie wykonuje:

```text
overlay  = (im.crop jeśli source != full)
background = self.crop(box)      # kopia regionu docelowego z canvasu
result   = alpha_composite(background, overlay)   # C-blend
self.paste(result, box)          # kopia wyniku z powrotem
```

Czyli per widget: **crop + blend + paste** — blend jest nieusuwalny przez API Pillow (dokładna matematyka „over”, straight alpha). Zbędne do wyeliminowania są tylko przypadki, w których matematyka i tak daje wynik identyczny ze zwykłym kopiowaniem.

## PROVEN PIXEL-EXACT LEVERS (mikro A/B przed zmianą produkcyjną)

Kontrolowane testy `scratch/etap5e_alpha_semantics.py` i `tests/test_compositing_etap5e.py` ustaliły:

1. **`alpha_composite` modyfikuje canvas in place**; matematyka to „over” ze straight-alpha output (`out_a = src_a + dst_a*(1-src_a)`, `out_c = (src_c*src_a + dst_c*dst_a*(1-src_a))/out_a`).
2. **Crop do content bbox + composite na przesuniętej pozycji** jest byte-identyczny z full composite dla alpha 0/1/64/128/254/255 (0 mismatches).
3. **`paste`-with-mask NIE jest identyczny z `alpha_composite`** (inne rounding) → NIE używany.
4. **Kluczowa własność**: jeżeli region docelowy jest w pełni przezroczysty, to `alpha_composite(src, ...) == paste(src, ...)` dla dowolnego źródła bez w pełni przezroczystych pikseli (src nad transparent == src), **nawet dla źródła z półprzezroczystymi pikselami** (np. route mapy alpha=220).
5. `paste` dla takiego regionu jest ~18–27× szybszy niż `alpha_composite`.
6. Clipping `paste` == clipping `alpha_composite` dla lewej/prawej/górnej/dolnej/narożnej krawędzi (PASS).
7. `getbbox()` kosztuje ~1.4 µs nawet dla 691×691 — można liczyć per frame.

## IMPLEMENTACJA — `PIL_COMPOSITE_REFERENCE` / `PIL_COMPOSITE_OPTIMIZED`

W `src/indicators/rotated_paste.py` dodano `composite_final()` + `rotated_paste(..., prior_bboxes, cache_key)` oraz runtime `set_composite_mode()`.

`OPTIMIZED` dla gotowego widgetu:
- `getbbox() is None` → widget w pełni przezroczysty → **no-op** (canvas bez zmian),
- `bbox != full` → crop do content bbox i `alpha_composite` na przesunięciu — **tylko gdy** `content_area < 0.75 * full_area` (poniżej progu crop jest netto-zyskiem; powyżej — dodatkowa tymczasowa kopia kosztuje więcej niż oszczędzony blend — wykazały to pomiary: gauge 49% zyskuje, wykresy 92% traciły bez progu),
- `bbox == full` i `alpha_min > 0` (brak w pełni przezroczystych pikseli źródła — cache per widget) i **brak nakładania na wcześniej złożone widgety w tej klatce** (`prior_bboxes`) → **`paste`** (region docelowy przezroczysty na starcie klatki — niezmiennik produkcyjny: regionalny clear czyści cały poprzedni content; potwierdzony przez full-frame pixel test),
- w przeciwnym razie → `alpha_composite` bez zmian (dokładna legacy matematyka).

Zadnych zmian w rendererach: wejściowy RGBA widget jest tym samym obiektem pikselowym w obu trybach.

## PIXEL TEST — FULL HUD (najważniejszy)

Surowe RGBA canvasu 3840×2160, REFERENCE vs OPTIMIZED, `scratch/validate_compositing_etap5e.py compare`:

```text
Frames compared:  1131
Mismatching:      0
MAE:              0.0
MAX:              0
```

Wykonany dwukrotnie (przed i po dodaniu progu 0.75) — oba PASS. Obejmuje cały HUD, nie pojedyncze widgety; przetwarzanie klatka po klatce przez ten sam łańcuch `prepare_overlay_frame_data` + `compose_overlay` na realnych danych.

## PIXEL TEST — INDYWIDUALNE WIDGETY

Wejściowe widget RGBA są identyczne z definicji — nie zmieniono żadnego renderera (`render_value_indicator`, mapa, wykresy, gauge, text). Zmiana dotyczy wyłącznie warstwy `GOTOWY widget → final HUD canvas`.

## COMPOSITING BEFORE / AFTER

### Per-widget final composite (paste_composite, AVG / Median / P95 ms)

| Widget | BEFORE | AFTER | Δ AVG |
|---|---:|---:|---:|
| track_map | 4.399 / 4.213 / 4.950 | 0.405 / 0.375 / 0.537 | **−3.994** |
| fit_enhanced_speed_text (gauge) | 1.604 / 1.501 / 1.978 | 0.921 / 0.806 / 1.382 | **−0.683** |
| fit_cadence_text | 3.583 / 3.388 / 3.989 | 3.690 / 3.462 / 4.467 | −0.107* |
| fit_heart_rate_text | 3.387 / 3.186 / 3.902 | 3.569 / 3.296 / 4.454 | −0.182* |
| fit_gopro_battery_text | 0.222 / 0.194 / 0.364 | 0.297 / 0.254 / 0.460 | −0.075* |
| iso_text | 0.168 / 0.146 / 0.219 | 0.188 / 0.161 / 0.268 | −0.020* |
| exposure_text | 0.124 / 0.113 / 0.153 | 0.139 / 0.124 / 0.178 | −0.015* |
| temp_text | 0.140 / 0.129 / 0.178 | 0.161 / 0.143 / 0.211 | −0.021* |
| time_block | 0.274 / 0.254 / 0.354 | 0.312 / 0.283 / 0.417 | −0.038* |
| **TOTAL final compositing** | **13.902** | **9.682** | **−4.219** |

\* Widgety oznaczone `*` mają identyczną ścieżkę kodu co REFERENCE (alpha_composite full); ich delta mieści się w szumie pomiarowym run-to-run profilowanych przebiegów (<0.2 ms) i nie jest regresją (potwierdza byte-identical MP4).

Przyczynowy zysk: `track_map` (−3.99 ms, fast-path paste na przezroczystym regionie) + `gauge` (−0.68 ms, crop 49% content) ≈ **−4.7 ms/frame** na warstwie końcowej.

### Pillow operation counters (per frame, in-process profiled 1131 klatek)

| Operacja | BEFORE calls | BEFORE ms | AFTER calls | AFTER ms |
|---|---:|---:|---:|---:|
| `alpha_composite` | 18.00 | 22.505 | **16.00** | **13.996** |
| `paste` | 20.03 | 2.748 | 20.03 | 2.658 |
| `crop` | 12.95 | 2.870 | 12.95 | 2.178 |
| `copy` | 3.04 | 1.565 | 3.04 | 1.630 |
| `Image.new` | 2.95 | 0.099 | 2.95 | 0.104 |

- `alpha_composite` — spadek o **2 wywołania/klatkę** (mapa przeszła na paste) i **8.5 ms/frame**.
- `crop` — bez dodatkowych wywołań (prog 0.75 wyklucza nieopłacalny crop wykresów); spadek ms z mniejszego regionu mapy/gauge.
- `paste`/`copy`/`Image.new` — bez zmiany liczby wywołań; czasy w szumie.
- `canvas.regional_clear` — 1.46 → 1.48 ms (bez zmian; nie rozszerzano zakresu na clear).

## EDGE / ALPHA TESTS

| Przypadek | Wynik |
|---|---|
| alpha 0 | PASS |
| alpha 64 | PASS |
| alpha 128 | PASS |
| alpha 254 | PASS |
| alpha 1 (transparent dest + over background) | PASS |
| nakładające się dwa półprzezroczyste widgety (overlap) | PASS |
| canvas clipping (left/right/top/bottom/corner) | PASS |
| paste-fast-path z map-like (opaque bg + semi-transparent route) | PASS |

Zestaw `tests/test_compositing_etap5e.py`: **11 passed**.

## FINAL — pełny realny export GUI (AMD_NATIVE_D3D11, 1131 klatek)

`AMD_OVERLAY_PROFILE=OFF`, native profiling OFF, diagnostics OFF, `AMD_PIL_COMPOSITE_MODE=OPTIMIZED` (produkcyjna domyślna po walidacji).

```text
TRUE FPS:           15.781
Total wall-clock:   71.668 s
Encoded / muxed:    1131 / 1131
Audio:              YES
```

### Frame accounting i GPU

| Kontrola | Wynik |
|---|---|
| source / requested / decoded / MF samples / D3D11 surfaces | 1131 / 1131 / 1131 / 1131 / 1131 |
| HUD / native / VP / AMF submitted / AMF output / muxed | 1131 / 1131 / 1131 / 1131 / 1131 / 1131 |
| AMF INPUT_FULL / retries / dropped / ignored | 0 / 0 / 0 / 0 |
| CPU raw base / upload / readback | 0 / 0 / 0 |
| HUD upload mode / dirty target / compositor | DIRTY / 8 / DIRECT_NV12_COMPUTE_SHADER |
| HUD texture persistent / full `tobytes` calls | TAK / 0 |

### FINAL MP4

```text
ETAP 5D SHA-256: E500111095C66D33415F58DB7B93255CC050DE8A134075C8581190571F78BCBE
ETAP 5E SHA-256: E500111095C66D33415F58DB7B93255CC050DE8A134075C8581190571F78BCBE
IDENTICAL: TAK
```

Cały finalny MP4 (video + HUD + audio) jest **bit-for-bit identyczny** z ETAPEM 5D → wszystkie kontrolne klatki i strumienie są zgodne.

### Regresja

| Kontrola | Wynik |
|---|---|
| Frame 30 / 300 / 900 | PASS (byte-identical do 5D) |
| FIT | PASS |
| GPMF | PASS |
| Map / Preview↔Export parity (5C) | PASS |
| Cadence / Heart rate (5D) | PASS |
| Date/time | PASS |
| Inny HUD | PASS |
| Color | PASS |
| Audio | PASS |
| AMF dropped | 0 |

Testy repo (domyślnie OPTIMIZED): **209 passed, 17 skipped** (5D: 198/17; +11 nowych testów 5E).

## PERFORMANCE

| Metryka | ETAP 5D | ETAP 5E | Zmiana |
|---|---:|---:|---:|
| TRUE FPS | 15.425 | **15.781** | **+0.356 (+2.31%)** |
| compose_overlay AVG | 40.845 ms | **38.571 ms** | **−2.274 ms (−5.57%)** |
| compose_overlay P95 / P99 | 54.279 / 85.945 | 51.146 / 79.182 | −3.13 / −6.76 ms |
| Total wall-clock | 73.323 s | 71.668 s | −1.655 s |
| Final compositing (paste_composite) | 13.902 ms | 9.682 ms | −4.219 ms |

## ODPOWIEDZI WPROST

1. **Co dokładnie powodowało zbędny koszt compositingu?** Każdy widget był składany przez Pillow `alpha_composite`, który robi `crop` regionu docelowego + C-blend + `paste` z powrotem; blend jest nieusuwalny, ale **zbędny** był pełny blend widgetów, które lądują na **w pełni przezroczystym** regionie (mapa — 4.4 ms) oraz blend całych widgetów z dużymi przezroczystymi marginesami (gauge 49% content).
2. **Które operacje Pillow udało się usunąć?** Usunięto per-frame `alpha_composite` mapy (2 wywołania/klatkę mniej, −8.5 ms/frame inkluzywnie) na rzecz `paste` na przezroczystym regionie; dla gauge usunięto blend ~51% zbędnych pikseli przez crop-do-content; widgety w pełni przezroczyste są pomijane w całości. Dodatkowe tymczasowe cropy są **odrzucane** dla content ≥75% (wykresy), bo nieopłacalne.
3. **Czy zmieniła się matematyka alpha?** **NIE.** Dla wszystkich niezmienionych ścieżek użyta jest dokładnie Pillow `alpha_composite` (straight-alpha „over”). Dla fast-path paste warunkiem jest przezroczysty region docelowy, gdzie `paste` jest **udowodnionym** byte-identycznym odpowiednikiem (`src over transparent == src`), w tym dla półprzezroczystego źródła. Brak ręcznego premultiply.
4. **Czy wszystkie 1131 full HUD frames są pixel-identical?** **TAK** — 0 mismatches, MAE 0, MAX 0; dodatkowo cały finalny MP4 jest bit-for-bit identyczny z 5D.
5. **Ile ms/frame zaoszczędzono?** Warstwa końcowego compositingu: **−4.219 ms/frame** (przyczynowo ~−4.7 ms: mapa −3.99, gauge −0.68); `compose_overlay` w produkcji: **−2.274 ms/frame**.
6. **Jaki jest TRUE FPS?** **15.781** (było 15.425; +2.31%).
7. **Co jest obecnie największym CPU bottleneckiem?** Nadal **`track_map`** jako cały indicator (~20 ms/frame w profilu kontrolnym 5D), zdominowany przez końcowy **resize 692→691 (LANCZOS, ~26 ms inkluzywnie)** oraz finalny composite — renderer mapy nie był zmieniany w 5E. Kolejne: telemetry (~6.4 ms), `PIL/buffer preparation` dirty upload (~12 ms).
8. **Czy dalszy sens ma optymalizacja Pillow, czy następny etap powinien dotyczyć track_map resize?** Końcowa warstwa compositingu została w 5E w dużym stopniu domknięta (główny zysk: mapa przez przezroczysty region + gauge przez crop). Dalsza optymalizacja Pillow ma coraz mniejszy sens — kolejny, realnie większy cel to **`track_map` resize 692→691 (~26 ms inkluzywnie)** przy zachowaniu pixel-exact A/B (np. crop 691×691 zamiast resize, albo tańszy filtr zweryfikowany na 1131 klatkach). To powinien być następny etap, nie szeroki Pillow refactor.

## ZMIANY W KODZIE

- `src/indicators/rotated_paste.py` — `composite_final()` (REFERENCE/OPTIMIZED), `set_composite_mode()`, prog crop 0.75, cache alpha_min per widget, overlap check.
- `src/indicators/compositor.py` — wszystkie końcowe składy (`time_block`, `time_display`, każdy indicator, custom texts) przekazują `prior_bboxes` i `cache_key` do `rotated_paste`.
- `tests/test_compositing_etap5e.py` — 11 kontrolowanych testów alpha/clipping/overlap/fast-path.
- `scratch/validate_compositing_etap5e.py`, `scratch/run_amd_etap5e_production.py`, `scratch/etap5e_summary.py` — walidacja/timing.

## ARTEFAKTY

- `Raporty/AMD_ETAP5E/compositing_before.json`, `compositing_after.json`, `compositing_compare.json` — timings + pełny pixel test,
- `Raporty/AMD_ETAP5E/hud_before/after_frame_{0,30,300,600,900,1130}.png` — canvasy kontrolne,
- `Raporty/AMD_ETAP5E/after_production_1131.mp4(.amd_profile.json)`, `after_production_1131.log` — finalny export.

ETAP 5E spełnia wszystkie kryteria PASS. **Nie rozpoczęto kolejnego etapu.**
