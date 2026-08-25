# Raport: ETAP 10R — AMD ABOVE — EXACT tight bbox propagation (Variant A)

**Data pomiaru:** 2026-08-22
**Typ zadania:** `IMPLEMENTACJA` (EXACT / Variant A po audycie 10P i porażce CANDIDATE w 10Q)
**Agent:** GitHub Copilot (DeepSeek V4 Flash)
**Preset bazowy:** `presets/cycling_dashboard_v10.json`
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`
**Benchmark:** AMD Native D3D11VA + AMF HEVC, 1280×720 @ 60 FPS, 120 klatek, pełny v10
**Zakres:** `src/indicators/compositor.py`, `src/indicators/rotated_paste.py`, `src/ffmpeg/amd_native_exporter.py` + targetowane testy

---

## 1. Exact architecture

Nowy tryb `AMD_ABOVE_DIRTY_MODE=EXACT` (Variant A — FAST EXACT DIRTY BBOX) dla `CPU_ABOVE_MAP`:

```
compose_overlay(..., _bboxes=declared, _tight_bboxes=tight)   # compositor.py
  └─ rotated_paste -> composite_final(..., tight_bboxes)      # rotated_paste.py
       └─ alpha-tight bbox rastra (po rotacji) + offset        # {"rect"|None, "clipped"}
_cluster_above_bboxes_members(declared)                        # (rect, members) — identyczne klastry jak SCAN
_extract_exact_above_regions(above_full, members, tight)      # union tight bboxów per klaster -> crop -> tobytes
  └─ fallback per klaster -> SCAN (candidate -> alpha scan -> tight crop)
```

Kluczowy invariant: **EXACT upload region == SCAN tight alpha region** (geometria i piksele), bo geometria regionu jest używana przez `ClearPreviousAboveMap` (erase) — różnica zmieniłaby finalny raster (błąd CANDIDATE z 10Q).

---

## 2. Changed production files

| Plik | Zmiana |
|---|---|
| `src/indicators/rotated_paste.py` | `composite_final`/`rotated_paste` z opcjonalnym `tight_bboxes`/`tight_key`: alpha-tight bbox rastra (po rotacji) w absol. współrzędnych canvasu + flaga `clipped`. Akumulator `above_tight_bbox_collect`. Gdy `tight_bboxes=None` — 100% bez zmian. |
| `src/indicators/compositor.py` | `compose_overlay(..., _tight_bboxes=None)` (addytywnie) przekazywane do wszystkich `rotated_paste` (time_block/time_display/indicators/custom_texts). Gdy `None` — 100% bez zmian. |
| `src/ffmpeg/amd_native_exporter.py` | `_resolve_above_dirty_mode` akceptuje EXACT; `_cluster_above_bboxes_members`; `_extract_exact_above_regions` (+ fallback SCAN per klaster); producent EXACT; metryki `above_tight_bbox_collect`/`above_exact_union`/`above_exact_crop`; liczniki fallbacku; profil `etap8n`; default `EXACT`. |

NIE zmieniono: natywne DLL, D3D11 C++, NVIDIA, FIT, TelemetryManager, SmartSync, map renderer, chart/bar/gauge/text renderery, presets, GUI.

---

## 3. Source of tight bbox

Tight bbox jest pozyskiwany w `composite_final` (`rotated_paste.py`) — **na rastrze widgetu po rotacji**, w miejscu dokładnego paste (zna `x`, `y`, `overlay.width/height`). To ponowne użycie już przygotowanego, wyrotowanego rastra — bez dużego skanu candidate canvasu. Koszt mierzony jako `above_tight_bbox_collect`.

Nie użyto `overlay.getbbox()` (RGBA) jako źródła — patrz §4.

---

## 4. Alpha semantics

Canonical definition (identyczna z SCAN): **tight bbox = bounding box pikseli gdzie `alpha != 0`**.

`composite_final` używa `overlay.getchannel("A").getbbox()` (alpha-tight), a NIE `overlay.getbbox()` (RGBA), ponieważ piksel z `A=0, RGB!=0` jest pomijany przez SCAN (`getchannel("A").getbbox()`), a RGBA `getbbox()` by go uwzględnił. Test `test_exact_alpha_tight_ignores_a0_rgb_nonzero` to potwierdza: dirty-zero narożniki są wykluczone identycznie jak w SCAN.

---

## 5. Coordinate transformations

Tight bbox widgetu = `alpha_bbox(wyrotowany raster) + (x, y)` gdzie `x, y = round(center - dim/2)` (dokładnie jak `rotated_paste`). Wartość zapisywana jest w absol. współrzędnych canvasu (po odjęciu `coordinate_origin`), spójnie z `_bboxes` i `above_full`. Union per klaster jest klipowany do canvasu (`_clip_rect(pad=0)`).

---

## 6. Rotation handling

- `composite_final` otrzymuje raster **po transpozycji** (0/90/180/270), więc tight bbox jest liczony na faktycznie wyrotowanym rastrze — transformacja jest dokładna (transpose bez resamplingu), bez matematycznej konwersji bboxa.
- `rotation=90` (alt_visual): tight bbox po rotacji pokrywa się ze SCAN (test `test_exact_parity_rotations_90_180_270` + realny `alt_visual` w parity).
- Non-ortogonalna rotacja: nie występuje w rendererach (wszystkie używają transpozycji 0/90/180/270). Gdyby pojawiła się inna, `rotated_paste` i tak transponowałby tylko 0/90/180/270; brak obsługi arbitralnego kąta = spójne z SCAN (SCAN też nie obraca arbitralnie).

---

## 7. Cluster membership handling

`_cluster_above_bboxes_members` powtarza **dokładnie** reguły `_cluster_above_bboxes` (pad=16, merge_dist=32, max_regions=16), dodając śledzenie kluczy. Test `test_cluster_members_match_plain_clustering` oraz realny parity (`cluster_rect_fail=0` na 120 klatkach) potwierdzają identyczne candidate rects. Dla każdego klastra: `exact_cluster_bbox = union(tight_bbox(member_1), ...)` bez dodatkowego paddingu. Żadnej intersection-heuristic.

---

## 8. Fallback rules

`_extract_exact_above_regions` — per klaster, jeżeli:

```
missing_tight_bbox   (member bez wpisu w tight_bboxes)
clipped_widget       (paste wystaje poza canvas -> bbox przyciętego contentu może różnić się od przyciętego bboxa)
invalid_exact_rect   (union po klipowaniu pusty/poza canvasem)
```

→ ten klaster przechodzi na SCAN (candidate → `getchannel("A")` → `getbbox` → tight crop → tobytes). Brak crash; brak spamu logów — powody agregowane w `above_exact_fallback_reason`.

---

## 9. SCAN vs EXACT region parity (real data, 120 klatek)

Porównano **faktyczną geometrię i bajty regionów uploadu** (nie tylko zrekonstruowany overlay — to był błąd 10Q):

```
cluster_rect_fail = 0   (klastry identyczne)
region_fail       = 0   (count, x, y, width, height)
byte_fail         = 0   (RGBA bytes)
exact_clusters_total = 120, scan_fallback_total = 0
SCAN uploaded_px/frame == EXACT uploaded_px/frame == 543600
```

**PASS** — SCAN i EXACT produkują byte-for-byte identyczne regiony uploadu.

---

## 10. Region-coordinate examples

Z diagnostyki 10Q (klatka 30, realny v10):

```
SCAN tight region:  (45, 54, 906, 600)   [543600 px, 30292 px alpha>0]
EXACT region:       (45, 54, 906, 600)   [identycznie]
```
(EXACT region pochodzi z unii tight bboxów memberów klastra; dla v10 klaster = 1.)

---

## 11. Byte parity

Dla każdego regionu `r_bytes` identyczne (byte-for-byte) — potwierdzone `byte_fail=0` na 120 klatkach oraz testami jednostkowymi (`_assert_region_parity`).

---

## 12. Transparent RGB / A=0 test

`test_exact_alpha_tight_ignores_a0_rgb_nonzero`: raster z pikselami `R,G,B != 0, A = 0` w paddingu → tight bbox je pomija (rect = (150,85,101,31), bez narożników) identycznie jak SCAN.

---

## 13. Dynamic widget tests

`test_exact_dynamic_text_width_parity` (wąski↔szeroki tekst) i `test_exact_moving_marker_parity` (marker A→B) — EXACT region podąża za SCAN w każdej pozycji/szerokości. Realny 120-klatkowy parity pokrywa: HR/Cadence cursor, Distance, Slope, Compass, Virtual Power, Speed Gauge, ISO, Shutter, Temperature, Altitude(90°).

---

## 14. None transitions

`test_exact_none_transition_no_region`: w pełni przezroczysty widget → SCAN i EXACT nie generują regionu (uploaded_pixels=0). Realny v10 w oknie 2 s nie ma przejścia None (wartości ciągłe) — spójne z 10Q.

---

## 15. Overlap

`test_exact_parity_overlap` i `test_exact_parity_multiple_widgets_merged`: nakładające się / bliskie widgety scalone w 1 klaster → union tight bboxów == SCAN alpha bbox całego klastra.

---

## 16. Altitude 90°

`test_exact_parity_rotations_90_180_270` + realny `alt_visual` (rotation=90) w 120-klatkowym parity → EXACT == SCAN.

---

## 17. Map underneath

Ponieważ EXACT uploaduje **identyczne** regiony jak SCAN (geometria i piksele), `ClearPreviousAboveMap` kasuje identyczny obszar — brak różnic w mapie pod spodem. Potwierdzone finalnym GPU parity (wszystkie 120 klatek byte-identical, mapa w pełni pokryta).

---

## 18. Final GPU parity — 120 frames

Decoded RGBA (ffmpeg, wszystkie 120 klatek) porównane piksel-po-pikselu:

```
SCAN#1 vs SCAN#2 (encoder determinism control): frames_diff=0/120 diff_pixels=0 max_delta=0
SCAN vs EXACT (final GPU parity):               frames_diff=0/120 diff_pixels=0/110592000 (0.000%) max_delta=0
SCAN#2 vs EXACT (cross-check):                  frames_diff=0/120 diff_pixels=0 max_delta=0
```

**PASS** — finalny raster (video + map + HUD + ABOVE) jest identyczny we wszystkich 120 klatkach.

---

## 19. Ghosting

- Region parity (identyczna geometria regionów) ⇒ identyczne `m_abovePrevRegions` ⇒ identyczny erase `ClearPreviousAboveMap`.
- Final GPU parity (120/120 byte-identical) potwierdza brak ghostingu dla przypadków: marker L→R/R→L, tekst szerszy→węższy, value→None/None→value, pozycja A→B (pokryte testami + realnym materiałem).
- **0 stale pixels** (diff_pixels=0 w finalnym rastrze).

---

## 20. SCAN benchmark (2 świeże runy, 120 klatek)

| Metryka | run1 avg / med | run2 avg / med |
|---|---:|---:|
| `above_bbox_tracking` | 0.066 / 0.054 | 0.061 / 0.054 |
| `above_candidate_crop` | 0.663 / 0.600 | 0.654 / 0.604 |
| `above_local_alpha_scan` | 0.318 / 0.278 | 0.326 / 0.275 |
| `above_final_crop` | 0.443 / 0.409 | 0.456 / 0.406 |
| `above_region_to_bytes` | 0.874 / 0.828 | 0.870 / 0.819 |
| `above_region_upload` | 0.259 / 0.213 | 0.257 / 0.221 |
| dirty (crop+scan+final+tobytes) | 2.298 / 2.115 | 2.306 / 2.104 |
| Render FPS | 41.36 | 41.37 |
| TRUE FPS | 14.58 | 14.28 |

uploaded_pixels=543600, uploaded_bytes=2174400.

## 21. EXACT benchmark (2 świeże runy)

| Metryka | run1 avg / med | run2 avg / med |
|---|---:|---:|
| `above_bbox_tracking` | 0.064 / 0.055 | 0.060 / 0.054 |
| `above_tight_bbox_collect` | 0.272 / 0.211 | 0.237 / 0.203 |
| `above_candidate_crop` | 0.000 | 0.000 |
| `above_local_alpha_scan` | 0.000 | 0.000 |
| `above_final_crop` | 0.000 | 0.000 |
| `above_exact_union` | 0.024 / 0.020 | 0.021 / 0.019 |
| `above_exact_crop` | 0.604 / 0.551 | 0.566 / 0.535 |
| `above_region_to_bytes` | 0.916 / 0.824 | 0.864 / 0.808 |
| `above_region_upload` | 0.283 / 0.228 | 0.336 / 0.214 |
| dirty (collect+union+crop+tobytes) | 1.816 / 1.606 | 1.688 / 1.565 |
| Render FPS | 37.64 | 40.95 |
| TRUE FPS | 14.08 | 14.54 |

uploaded_pixels=543600 (identycznie jak SCAN), uploaded_bytes=2174400.

## 22. Performance delta

```
dirty path:  SCAN ≈ 2.30 avg / 2.11 med   →   EXACT ≈ 1.75 avg / 1.59 med
             Δ ≈ −0.55 ms/frame avg  (−0.52 med)
```

- `above_local_alpha_scan` i `above_final_crop` = 0 (całkowicie pominięte); `above_candidate_crop` = 0.
- Koszt EXACT: `above_tight_bbox_collect` (~0.25 ms — per-widget alpha scans w composite_final) + `above_exact_crop` (~0.58 ms, crop tight z pełnego canvasu) + `above_exact_union` (~0.02 ms).
- **Render/TRUE FPS: neutralne (w granicach szumu)** — zysk ~0.5 ms to ~3.5% budżetu klatki (~14 ms), a FPS między świeżymi procesami jest zaszumiony (warm-up cache chartów).

Rzeczywisty zysk (~0.5 ms) jest mniejszy niż szacunek 10P (1.0–1.1 ms), głównie przez koszt `tight_bbox_collect` i wyższy `exact_crop` (crop z pełnego 1280×720 zamiast z candidate).

## 23. Frame accounting

Oba tryby:

```
decoded = 120, submitted = 120, encoded = 120, muxed = 120
→ 120 / 120 / 120 / 120 (PASS)
```

## 24. Fallback count

```
above_exact_clusters        avg = 1.0 / frame
above_scan_fallback_clusters avg = 0.0 / frame
above_exact_fallback_reason = {}   (0 fallbacków na 120 klatek)
```
Wszystkie widgety v10 są exact-safe (w pełni w canvasie, tight bboxy kompletne).

## 25. Final default

```
AMD_ABOVE_DIRTY_MODE_DEFAULT = "EXACT"
```
Ustawione po przejściu wszystkich bramek (§36): region parity PASS, final GPU parity PASS (120/120), ghosting PASS, map-underneath PASS, frame accounting PASS. `SCAN` pozostaje w pełni dostępny przez `AMD_ABOVE_DIRTY_MODE=SCAN`.

## 26. Remaining bottleneck

```
above_region_to_bytes   ~0.87–0.92 ms   (kopia RGBA → bytes; nieuniknione bez zmiany buffer contract)
above_exact_crop        ~0.57–0.60 ms   (crop tight z pełnego canvasu)
above_tight_bbox_collect ~0.24–0.27 ms  (per-widget alpha scans)
above_region_upload     ~0.26–0.34 ms   (w tym from_buffer_copy)
above_compose           ~11.6–13.5 ms   (render ABOVE — dominujący)
```

Największy pozostały bottleneck to `above_compose` (render ABOVE) oraz `above_region_to_bytes`.

## 27. Recommended next target

1. **`above_region_to_bytes` / `above_region_upload`** (Variant C — reuse bufora ctypes `from_buffer_copy`): ortogonalne, ~0.2–0.3 ms, niskie ryzyko.
2. **`above_tight_bbox_collect`** — redukcja per-widget alpha scans (reuse `_alpha_min`/clean-transparency cache dla widgetów o statycznej geometrii; tight bbox tylko dla dynamicznych) — zysk ~0.15–0.25 ms.
3. **`above_exact_crop`** — crop tight z `above_full` (pełny canvas) jest droższy niż z candidate; można rozważyć crop z mniejszego źródła (jeśli bezpieczne).
4. **`above_compose`** (render ABOVE) — osobny temat (wykresy/gauge).

Nie rekomenduje się CANDIDATE (10Q: unsafe GPU erase). Variant C (buffer reuse) można łączyć z EXACT.

---

## Final status

```
AMD ABOVE EXACT TIGHT BBOX: CORRECT BUT LOW IMPACT
```

Uzasadnienie:
- **region parity: PASS** (120/120, byte-for-byte geometria + bajty),
- **final GPU parity: PASS** (120/120 klatek decoded, diff_pixels=0, max_delta=0),
- **ghosting / map-underneath / frame accounting: PASS** (120/120/120/120),
- **zysk: ~0.5 ms/frame** w dirty path (mniejszy niż szacowane 1.0–1.1 ms), Render/TRUE FPS neutralne.

Ponieważ poprawność jest kompletna, a zysk umiarkowany — zgodnie z §43:

```
AMD ABOVE EXACT TIGHT BBOX: CORRECT BUT LOW IMPACT
```

Default ustawiony na `EXACT` (§36: wszystkie bramki poprawności przeszły). `SCAN` wymuszany przez env.

---

## Repo safety

```
git status     — zmiany: amd_native_exporter.py, compositor.py, rotated_paste.py, nowy test, raport; temp scratch usunięte
git diff       — tylko zamierzone zmiany ETAP 10R (potwierdzone)
git diff --check — brak błędów whitespace
```

Tymczasowa instrumentacja (benchmark/parity/export/compare + MP4/profile) **usunięta przed zakończeniem** (`Get-ChildItem scratch -Filter *etap10r*` → 0).

NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.
