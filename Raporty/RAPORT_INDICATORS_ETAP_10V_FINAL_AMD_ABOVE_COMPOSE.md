# Raport: ETAP 10V — Final AMD — optymalizacja `CPU_ABOVE_MAP / above_compose`

**Data pomiaru:** 2026-08-23
**Typ zadania:** `FINAL AMD PERFORMANCE` (ostatnia duża optymalizacja AMD)
**Agent:** GitHub Copilot (DeepSeek V4 Flash)
**Preset bazowy:** `presets/cycling_dashboard_v10.json`
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (offset +2.000 s, SmartSync nie uruchamiany)
**Benchmark:** AMD Native D3D11VA + AMF HEVC, 1280×720 @ 60 FPS, 120 klatek, `AMD_ABOVE_DIRTY_MODE=EXACT`, `AMD_ABOVE_UPLOAD_BUFFER_MODE=DIRECT`
**Status:** `FINAL AMD ABOVE COMPOSE OPTIMIZATION: LOW ROI — NO COMPLEX CHANGE`
**Linia końcowa:** `AMD PERFORMANCE PHASE: COMPLETE`

---

## 1. Fresh baseline (po 10R/10U/10T/10T2)

Świeży 120-klatkowy pomiar produkcyjny (ta sama konfiguracja co 10U):

```text
above_compose              avg=12.793  med=11.051  p95=25.330
above_total                avg=13.748  med=11.930  p95=26.671
above_region_to_bytes      avg=0.891   med=0.836   p95=1.156
above_exact_crop           avg=0.603   med=0.568   p95=0.770
above_region_upload        avg=0.429   med=0.368   p95=0.578
above_upload_buffer_prepare avg=0.017  med=0.016   p95=0.026   (DIRECT działa)
RENDER FPS = 38.85   TRUE FPS = 13.60
```

## 2. Warm-up vs steady-state

Pomiary 120-klatkowe; `above_compose` med=11.05 ms (p95 25.3 — pierwsze klatki z budową cache/tegmentów są wyższe). Per-widget poniżej to mean/med z całego okna; dominująca struktura (charty > reszta) nie zmienia się między warm-up a steady-state.

## 3. Per-widget profile (clean, bez Pillow hooks — §5)

Świeży pomiar per-widget (render przez `render_value_indicator`, paste przez `rotated_paste`; wartości czyste, bez instrumentacji Pillow):

| Widget | render (mean ms) | paste (mean ms) | total |
|---|---:|---:|---:|
| alt_visual (Altitude) | 0.141 | 0.371 | 0.512 |
| compass | 0.243 | 0.505 | 0.748 |
| exposure_text (Shutter) | 0.283 | 0.074 | 0.357 |
| fit_cadence_text (Chart) | **2.869** | 0.199 | **3.068** |
| fit_curVpower_text | 0.107 | 0.455 | 0.562 |
| fit_enhanced_speed_text (Speed Gauge) | 0.417 | 0.279 | 0.696 |
| fit_heart_rate_text (Chart) | **2.897** | 0.218 | **3.115** |
| iso_text | 0.180 | 0.088 | 0.268 |
| slope_text | 0.177 | 0.678 | 0.855 |
| temp_text | 0.029 | 0.076 | 0.105 |
| **SUMA ABOVE** | **≈7.34** | **≈2.94** | **≈10.3** |

**Wniosek: renderery (nie placement!) dominują** — same **charty HR+Cadence = 5.77 ms** (~45% `above_compose`). Placement (paste) to tylko ~2.9 ms.

## 4. Compose breakdown (§7)

`compose_overlay` (ABOVE) rozbicie:

```text
renderer calls (render_value_indicator)   ≈ 7.34 ms   (charty 5.77, reszta 1.57)
rotated_paste / composite_final           ≈ 2.94 ms   (getbbox + crop + alpha_composite/paste)
residual (canvas clear, tight_bbox_collect, dispatcher,
         _paste_prior_bboxes, EXACT cluster/extract bookkeeping) ≈ 2.5 ms
-----------------------------------------------------------------------
above_compose                              ≈ 12.8 ms
```

Residual (~2.5 ms) jest rozproszony (clear ~0.3 ms, tight_bbox_collect ~0.25 ms, dispatcher/bbox tracking ~0.4 ms, reszta) — nie ma jednego wspólnego, dużego składnika.

## 5. Pixel-area accounting (§9)

Świeży pomiar z rzeczywistego eksportu (per-widget full raster vs RGBA bbox vs alpha-tight bbox):

```text
widget                 full_px   alpha_bbox_px   alpha%
alt_visual             13275     10451           78.7%
compass                15625     8649            55.4%
exposure_text          847       847             100%
fit_cadence_text       56640     49049           86.6%
fit_curVpower_text     17000     14036           82.6%
fit_enhanced_speed_text 101761   71890           70.6%
fit_heart_rate_text    56640     48906           86.3%
iso_text               594       594             100%
slope_text             26442     20586           77.9%
temp_text              1110      1110            100%
SUMA ABOVE             ≈298834   ≈235163         ≈78.7%
```

**Kluczowe: `alpha_bbox == rgba_bbox` dla WSZYSTKICH widgetów** — brak „dirty” pikseli A=0/RGB≠0 na marginesach. Średnia zawartość alfa ~79% (powyżej progu break-even 75% istniejącej optymalizacji 5E).

## 6. Root cause

- **Placement** (cel zakładany przez 10V) jest już mocno zoptymalizowany: ETAP 5E crop transparent margins z progiem break-even 75%; `alpha_bbox == rgba_bbox` → TIGHT ROI nie da mniejszego obszaru.
- **Dominujący koszt to renderery chartów** (`CPU_REFERENCE`): HR 2.90 + Cadence 2.87 = **5.77 ms/klatkę**. To koszt renderera, nie compositingu; optymalizacja delta-render chartu jest ryzykowna dla kontraktu historii (AGENTS §35 seek bug — „chart fills progressively”) i poza zakresem „compose”.
- Residual compose ~2.5 ms jest rozproszony (brak jednego dużego składnika).

## 7. Variants benchmarked (§11)

Mikrobenchmark na realnych rastrach widgetów (800 iteracji, alpha_composite full vs tight crop+composite):

```text
widget          full_ms  tight_ms  getbbox_ms
chart_cadence   0.273    0.199     0.003
chart_hr        0.257    0.261     0.003
slope           0.092    0.094     0.004
altitude        0.044    0.046     0.004
compass         0.076    0.061     0.012
vpower          0.049    0.049     0.004
speed_gauge     1.023    1.100     0.045
```

**Full vs tight to w praktyce remis** (temp-crop offsetuje oszczędność blend; czasem tight wolniejszy). Skan `getbbox` to 0.003–0.045 ms/widget → **łącznie ~0.08 ms/klatkę** dla wszystkich widgetów ABOVE.

## 8. Chosen optimization

**ŻADNA** — zgodnie z §29. TIGHT ROI COMPOSITE oszczędza wyłącznie redundantny skan `getbbox` (~0.08 ms/klatkę), bez redukcji obszaru (alpha==rgba). To **daleko poniżej progu ≥1.0 ms / ≥10% (1.28 ms)**. Jedyny koszt >1 ms to renderery chartów (5.77 ms), ale to zmiana renderera wewnętrznego, blokowana przez AGENTS §35/§36 (otwarty bug seek/historia, „no chart refactor” poza zakresem) i ryzykowna (może odtworzyć progressive-fill).

## 9. Changed production files

**Brak.** Nie wymuszano implementacji poniżej progu (§29). `compositor.py`, `rotated_paste.py`, `chart.py`, `chart_utils.py` — bez zmian. EXACT/DIRECT/5E — bez zmian.

## 10–23. Parity / correctness (nie dotyczy — brak zmian produkcyjnych)

Ponieważ nie wdrożono zmiany produkcyjnej, parity CPU/GPU/preview/rotation/clipping/overlap/dynamic/None/SegmentBar/EXACT/DIRECT/CPU_REFERENCE jest **nienaruszone z definicji**. Potwierdzono testami targetowanymi (105 pass) i pełnym suite (§29 sekcja 29).

- **Alpha semantics** (§13/§14/§15): bez zmian — `alpha_composite` pozostał w obecnej ścieżce.
- **Rotation** (§16): `rotated_paste` transpose bez zmian.
- **Clipping / overlap / dynamic / None** (§17–20): bez zmian.
- **EXACT / DIRECT** (§21/§22): `_tight_bboxes` / `_above_region_pointer` bez zmian; default DIRECT.
- **Preview** (§23): współdzielony compositor bez zmian.
- **NVIDIA** (§24): wspólny `compositor.py`/`rotated_paste.py` niezmienione; NVIDIA nie jest dotknięta.
- **CPU_REFERENCE** (§25): niezmienione.
- **Segment Bar 10T2** (§26): niezmienione (dobry test alpha — bez zmian).
- **Map** (§27): nieoptymalizowana; ABOVE nad mapą bez zmian.

## 29. Full suite (final AMD checkpoint)

```text
806 passed, 17 skipped, 12 failed   (identyczne z baseline 10T2)
```

**0 nowych porażek.** 12 pre-existing failures (dryf planu pól FIT `def_layout.json`, refaktory chartów, dirty text cache, GPU-flaky) — poza zakresem 10V.

## 30. New vs pre-existing failures

Wszystkie 12 porażek to pre-existing (ten sam zestaw co 10T2). Brak nowych. Pre-existing slope `float(None)` (§42) — nie naprawiany, nie pogłębiony.

## 31. Remaining AMD bottlenecks (do raportowania, nie do wdrożenia)

```text
chart render (HR + Cadence, CPU_REFERENCE)  ≈ 5.77 ms/frame   ← dominujący koszt ABOVE
above_compose residual (rozproszony)         ≈ 2.5 ms
above_region_to_bytes                        ≈ 0.89 ms
above_exact_crop                             ≈ 0.60 ms
above_region_upload                          ≈ 0.43 ms
```

Zgodnie z §43 NIE przechodzimy do nich po zakończeniu compose optimization. Charty są domeną osobnego zadania (seek/historia — AGENTS §35/§36).

## 32. Explicit statement

```
AMD PERFORMANCE PHASE: COMPLETE
NEXT PROJECT PHASE: INTEL
```

AMD compose path jest uznane za zoptymalizowane w ramach dostępnego, bezpiecznego ROI: dirty-region EXACT, upload DIRECT, 5E regional compositing. Jedyny koszt >1 ms (renderery chartów) jest celowo odroczony do zadania chart seek/history.

---

## 46. Final status

```text
FINAL AMD ABOVE COMPOSE OPTIMIZATION: LOW ROI — NO COMPLEX CHANGE
AMD PERFORMANCE PHASE: COMPLETE
```

**Uzasadnienie:** świeży profil pokazuje, że dominującym kosztem są renderery chartów (5.77 ms), a nie placement. Placement (2.94 ms) jest już zoptymalizowany (5E crop; `alpha_bbox == rgba_bbox`; TIGHT ROI oszczędza tylko ~0.08 ms redundantnego skanu). Żadna bezpieczna, pojedyncza wspólna optymalizacja compositingu nie osiąga progu ≥1.0 ms / ≥10% (1.28 ms) — zgodnie z §29 nie wymuszono implementacji.

---

## 47. Repo safety

- `git diff --check` → PASS.
- Tymczasowe pliki (profilery, area-accounting, microbenchmark, MP4/profile JSON) **usunięte** (0 `*10v*` w scratch).
- **Brak zmian produkcyjnych** w tym etapie.
