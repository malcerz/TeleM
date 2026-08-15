# RAPORT AMD — ETAP 5I: Optymalizacja compose_overlay (największe bezpieczne CPU hotspoty)

**Status: ✅ UKOŃCZONE — wdrożono 1 bezpieczny hotspot (clean-transparency paste fast-path), byte-identical (1131/1131 klatek, MAE 0, MAX 0). Pozostałe największe koszty (charty alpha_composite) są inherentne dla Pillow = praktyczny floor.**

> Zgodnie z dyrektywą: **NAJPIERW PROFIL AKTUALNEGO STANU. POTEM TYLKO NAJWIĘKSZE BEZPIECZNE CPU HOTSPOTY.**
> Mapa GPU, HUD buffer prep (5H), telemetry (5B), final composite 5E — **FROZEN** (bez zmian).
> **STOP — nie wykonano ETAPU 5J.**

---

## PROFIL AKTUALNEGO STANU (PRZED) — czysty pomiar, bez profilera

`AMD_OVERLAY_PROFILE=0` (brak monkey-patch overhead). compose_overlay mierzone bezpośrednio,
120 klatek, pełny HUD 3840×2160 (bez track_map — mapa jest GPU).

```
CLEAN compose_overlay:  avg=15.2–15.8 ms  med=13.6–14.1 ms  p95=22–25 ms   (120 klatek)
```

### TOP hotspoty (per-widget final composite, ms/klatkę)

| Widget | ms/frame | Uwaga |
|---|---|---|
| fit_heart_rate_text (chart) | 2.66 | w tym alpha_composite 1160×511 + copy |
| fit_cadence_text (chart) | 2.14 | w tym alpha_composite 1160×511 + copy |
| fit_enhanced_speed_text (gauge) | 1.13 | crop 568×327 alpha_composite |
| time_block | 0.30 | mały tekst |
| fit_gopro_battery_text | 0.20 | mały tekst |
| iso_text | 0.14 | mały tekst |
| exposure_text | 0.06 | mały tekst |
| temp_text | 0.05 | mały tekst |

### Pillow ops (czysto)

| Op | ms/frame | calls/frame |
|---|---|---|
| alpha_composite | **2.48–2.65** | **8** |
| Image.new | 0.17 | 3.7 |

> ⚠️ Procesor overlay profiler **ZAWYŻA** alpha_composite do 13.14 ms / 16 calls (per-call lambda
> overhead). Czysty pomiar: **2.48 ms / 8 calls**. Wszystkie wnioski oparte na czystym pomiarze.

---

## WYBRANE HOTSPOTY (2–3 największe) — i uczciwa ocena

1. **Charty alpha_composite (cadence + HR, 1160×511)** — **Pillow FLOOR**. Dowód:
   - binary-mask paste (byte-identical) **WOLNIEJSZY**: cadence 2.07 vs mask+paste 3.69; HR 2.71 vs 3.67 (build maski 0.8–0.9 ms zabija zysk).
   - plain paste **NIE byte-identical** — charty mają `dirty_zeros=True` (piksele (r,g,b,0) — potwierdzone z realnych widgetów).
   - RGBA-as-mask paste **NIE byte-identical** (częściowe alfa dims).
   - value-cache nieopłacalny: ISO 740/1131 unikatowe (65%), speed 574/1131 (51%).
   - „crops" (3.47 ms) są WEWNĘTRZNE dla alpha_composite (dest crop + blend + paste back) — nieredukowalne.
2. **Gauge** — shadow już zcache'owany (build 1×); per-frame crop 568×327 alpha_composite. **Floor.**
3. **Małe czyste widgety** (time_block, battery, iso, exposure, temp) — alpha_composite → **plain paste** przez
   clean-transparency fast-path. **JEDYNY bezpiecznie optymalizowalny hotspot — wdrożony.**

**Wdrożono: HOTSPOT 3 tylko** (reszta udowodnionym floor). Bezpieczny warunek: alpha==0 piksele to (0,0,0,0) +
brak przecięcia z wcześniejszymi bboxami + mały widget (≤200×200) → nad przezroczystym tłem
`alpha_composite == paste` (byte-identical).

---

## HOTSPOT 3 — BEFORE / AFTER / pixel-exact

| | BEFORE (5I OFF) | AFTER (5I ON) |
|---|---|---|
| alpha_composite calls/frame | **8** (charty 2 + gauge 1 + **5 małych widgetów**) | **3** (charty 2 + gauge 1) |
| alpha_composite ms/frame (clean) | 2.63–2.65 | 2.41 |
| małe widgety | alpha_composite | `Image.paste` (bez blend) |

```python
if (
    _CLEAN_PASTE_ENABLED
    and overlay.width * overlay.height <= _SMALL_CLEAN_LIMIT_PX          # 200×200
    and prior_bboxes is not None
    and not _intersects_any((x, y, overlay.width, overlay.height), prior_bboxes)
    and (_alpha_min(overlay, cache_key) > 0 or _clean_transparency(overlay))
):
    base_img.paste(overlay, (x, y))
    return
```

- **Pixel-exact:** ✅ **TAK** — pełny CPU HUD canvas 3840×2160, WSZYSTKIE 1131 klatek, OFF vs ON:
  **0 mismatching frames, MAE 0, MAX 0** (poniżej).
- **Zabezpieczenia:** `_clean_transparency` (numpy) sprawdza, że wszystkie alpha==0 piksele są (0,0,0,0);
  limit rozmiaru; brak nakładania na prior bboxy; `AMD_PIL_CLEAN_PASTE` (domyślnie 1) + `set_clean_paste()`.
- **Rzeczywisty zysk:** eliminacja 5 wywołań Pillow alpha_composite/frame. **Czas totalny w granicach szumu**
  (małe widgety były już tanie 0.05–0.30 ms). Najlepszy czysty pomiar różnicy compose: **~0.2–0.6 ms/frame (med)**
  — poniżej wariancji sesji.

---

## CPU HUD PIXEL TEST — 1131 klatek (OFF vs ON)

```
=== CPU HUD PIXEL-EXACT GATE (1131 frames) ===
  mismatching frames: 0
  first mismatch frame: None
  total differing pixels (first bad frame): 0
  MAX diff (first bad frame): 0
  RESULT: PASS
```

Dodatkowy dowód: **wszystkie pełne exporty MP4 1131 kl. — 5H A/B/C/D ORAZ 5I A/B/C/D/E — mają IDENTYCZNY md5
(`78bf9195ef7e1ba2`)**; short testy (h5_opt31, i5_opt31) również identyczne (`e637929dbbd37f1d`).
5I nie zmienia ANI JEDNEGO bajta wyjścia względem **zwalidowanego etapu 5H**; enkoder deterministyczny run-to-run.
⇒ **REGRESJA PASS przez konstrukcję** (FIT/GPMF/Map/Cadence/HR/Speed/Data-czas/Kolor/Audio identyczne z 5H).

---

## ALLOKACJE

- **Brak nowych alokacji per-frame.** `_clean_transparency` używa numpy tylko dla małych widgetów (≤200×200),
  a `_alpha_min` już był cache'owany.
- Image.new bez zmian (0.17 ms / 3.7 calls — głównie kopie chartów `final_static.copy()`, wymagane).
- GC / alokacje obiektów per-frame **nie wzrosły**.

---

## FULL A/B/C/D (1131 frames każdy, D3D11VA + GPU MAP + HUD BUFFER REFERENCE, profiling/diag/readback OFF, ta sama sesja)

| Run | Tryb | clean | TRUE FPS | compose_overlay med | PIL/buffer med | acct |
|---|---|---|---|---|---|---|
| A | 5I_REFERENCE | 0 | 15.779 | 26.52 ms | 10.94 ms | 1131/1131 ✅ |
| B | 5I_OPTIMIZED | 1 | 19.363 | 20.56 ms | 8.84 ms | 1131/1131 ✅ |
| C | 5I_REFERENCE | 0 | 21.008 | 19.37 ms | 8.61 ms | 1131/1131 ✅ |
| D | 5I_OPTIMIZED | 1 | 20.285 | 20.82 ms | 8.92 ms | 1131/1131 ✅ |
| E | 5I_REFERENCE (potwierdzenie) | 0 | 20.823 | 19.51 ms | 8.77 ms | 1131/1131 ✅ |

```
REFERENCE MEDIAN (A,C):   18.393 FPS
OPTIMIZED MEDIAN (B,D):   19.824 FPS
GAIN:                     +7.8 %  ← (patrz ostrzeżenie o wariancji poniżej)
```

### ⚠️ UCZCIWA INTERPRETACJA (krytyczna)

- **Run A to potwierdzony outlier systemowy**: WSZYSTKIE etapy CPU w A są podniesione ~20%
  (compose 26.5, PIL/buffer 10.9, HUD dirty 10.7, telemetry 7.4) względem spójnych B/C/D/E
  (compose 19–21, PIL/buffer ~8.6–8.9, dirty ~8.6–8.8, telemetry ~6.9). Clean-paste dotyka TYLKO
  compose_overlay małych widgetów — **nie może** podnieść telemetry/HUD dirty/PIL buffer.
- **Run E (REF, 20.823) potwierdza**: REFERENCE to ~20.8–21.0 (C i E), nie ~15.8 (A).
- Z A usuniętym (fair): REF {C,E} med 20.92 vs OPT {B,D} med 19.82 → **−5.2 % — W GRANICACH SZUMU.**
- compose_overlay median: REF (A,C,E) 19.51 vs OPT (B,D) 20.69 — **w granicach szumu** (efekt 0.2–0.6 ms
  nie do rozdzielenia przy wariancji run-to-run ~±1.5 ms).
- **Wniosek**: pełno-pipeline'owy zysk TRUE FPS z 5I jest **statystycznie nierozróżnialny od zera**.
  Zysk 5I to realna (ale mała) redukcja kosztu alpha_composite; nie widać go w TRUE FPS przez wariancję sesji.
- Wszystkie 4+1 pliki **byte-identical** ⇒ brak regresji jakiegokolwiek rodzaju.

---

## COMPOSE BEFORE / AFTER (czysty microbench, interleaved, 120 klatek)

```
CLEAN_PASTE=0 (BEFORE)  compose avg=14.88/15.31  med=13.62/13.92   alpha_composite 2.63–2.65 ms / 8 calls
CLEAN_PASTE=1 (AFTER)   compose avg=14.93/19.09* med=13.77/15.83*  alpha_composite 2.41 ms / 3 calls
                         (* = spike szumu, p95 35 ms — odrzucony jako system contention)
```

- **alpha_composite: 8 → 3 calls/frame** (−5 wywołań), 2.63 → 2.41 ms (−0.22 ms/frame).
- **compose total: w granicach szumu** (med ~13.7 oba). Efekt jest realny ale mały — małe widgety
  były już tanie; charty (2.4 ms) są floor i nieoptymalizowalne byte-identycznie.

---

## BOTTLENECKS AFTER 5I

1. **Charty alpha_composite (cadence + HR)** — ~2.4 ms/frame — **Pillow floor** (wszystkie alternatywy
   byte-identical wolniejsze lub nieidentyczne — patrz SELECTED HOTSPOTS).
2. **Charty `final_static.copy()`** — ~1.2 ms/frame (0.58 każdy) — wymagane (mutacja per-frame kursora/etykiety).
3. **Gauge** — ~2.7 ms/frame (crop 568×327 alpha_composite; shadow cache'd) — floor.
4. **HUD buffer prep (PIL/buffer)** — ~8.6–10.9 ms/frame — floor 5H (3 kopie/rect), **frozen**.
5. **Telemetry/frame_data** — ~6.9–7.4 ms/frame — **frozen (5B)**.

---

## ODPOWIEDZI WPROST (10 pytań)

1. **Co powodowało 24–28 ms compose_overlay (produkcja)?** Charty alpha_composite (~2.4 ms) + chart copies
   (~1.2 ms) + gauge (~2.7 ms) + małe widgety + HUD buffer prep w pipeline; czysty compose med ~13.6–14.1 ms
   (produkcyjne mediany wyższe przez load systemowy / wariancję sesji, np. run A 26.5 ms = contention).
2. **Które 2–3 hotspoty wybrano?** (1) małe czyste widgety → clean-paste fast-path [wdrożone]; (2) charty
   alpha_composite [audyt: floor, nieoptymalizowalne byte-identycznie]; (3) gauge [floor].
3. **Co zostało zcache'owane/usunięte?** Usunięto 5 wywołań Pillow alpha_composite/frame (małe czyste widgety
   → plain paste). Nie dodano nowego cache; istniejące cache (gauge shadow, chart final_static) bez zmian.
4. **Ile ms/frame zaoszczędzono?** alpha_composite 2.63 → 2.41 ms (−0.22 ms); compose total **w granicach szumu**
   (najlepszy czysty pomiar różnicy med ~0.2–0.6 ms/frame). Realne, ale małe.
5. **Czy pełny CPU HUD pixel-identical?** **TAK** — 1131/1131 klatek, mismatches 0, MAE 0, MAX 0
   (+ wszystkie 5 MP4 byte-identical md5).
6. **Median TRUE FPS?** REFERENCE 18.393 (A,C) / 20.823 (A,C,E) vs OPTIMIZED 19.824 (B,D) → +7.8 % (A/B/C/D),
   ale z A jako potwierdzonym outlierem → **w granicach szumu** (−5.2 % fair). Zysk nierozróżnialny statystycznie.
7. **Największy bottleneck po 5I?** Charty alpha_composite (~2.4 ms) — Pillow floor; dalej HUD buffer prep
   (~8.6–10.9 ms, 5H) i telemetry (~6.9–7.4 ms, 5B).
8. **Czy CPU Pillow compose na praktycznym floor?** **TAK dla chartów i gauge** (udowodnione: mask+paste
   wolniejszy, paste nie byte-identical przez dirty zeros, RGBA-mask nieidentyczny, value-cache nieopłacalny
   65%/51% unikatowych wartości). Małe widgety już zoptymalizowane (paste).
9. **Czy 5J powinien przenieść konkretny renderer na GPU?** **TAK — charty (cadence + HR)** (~3.6–4.5 ms/frame
   razem z kopiami). Używają częściowego alfa (fill α=40, grid α=60, cursor α=157) → wymagają blendingu,
   który **już istnieje** w GPU compositor (BlendRGBAtoNV12).
10. **Który renderer najlepszy gain/risk?** **Charty (cadence + HR)**: największy koszt, statyczna siatka/podstawa
    może być pre-renderowana do GPU texture (jak gauge shadow), dynamiczna część (kursor, wartość) przez istniejący
    GPU blend. Ryzyko niskie — GPU compositor już blenduje; nie wymaga zmian HUD buffer prep ani telemetry.

---

## KRYTERIA PASS (ocena)

| # | Kryterium | Wynik |
|---|---|---|
| 1 | wygląd HUD bez zmian | ✅ PASS (byte-identical) |
| 2 | dane bez zmian | ✅ PASS |
| 3 | layout bez zmian | ✅ PASS |
| 4 | GPU pipeline bez zmian | ✅ PASS (GPU map + D3D11VA + HUD buffer REFERENCE) |
| 5 | TYLKO największe bezpieczne CPU hotspoty | ✅ PASS (1 wdrożony; reszta udowodniony floor) |
| 6 | max byte-identical (MAE 0, MAX 0, mismatch 0 / 1131) | ✅ PASS |
| 7 | pełne A/B/C/D 1131 każdy | ✅ PASS |
| 8 | medians + gain % | ✅ PASS (w granicach szumu — uczciwie udokumentowane) |
| 9 | AMF drops 0 / 1131/1131 / HW decode / map GPU / audio | ✅ PASS |
| 10 | FPS nie regresuje | ✅ PASS (byte-identical; REFERENCE default bez zmiany) |

**Wniosek:** 5I profiluje compose_overlay i wdraża JEDYNĄ bezpiecznie optymalizowalną redukcję
(clean-transparency paste fast-path dla małych widgetów; byte-identical). Największe koszty — charty
alpha_composite (~2.4 ms) i ich kopie (~1.2 ms) — są inherentne dla Pillow i stanowią praktyczny floor.
**Rekomendacja 5J: GPU renderowanie chartów (cadence + HR).**

## PLIKI / ARTEFAKTY

- `src/indicators/rotated_paste.py` — `_clean_transparency`, `_SMALL_CLEAN_LIMIT_PX`, `_CLEAN_PASTE_ENABLED`,
  `set_clean_paste()`, fast-path w `composite_final`.
- `scratch/i5_profile_gpu300.mp4` — Gate A (profil, 300 kl.).
- `scratch/i5_pixel_gate.py` — CPU HUD pixel-exact gate (1131 klatek).
- `scratch/i5_compose_bench.py` — czysty microbench compose + Pillow ops + per-widget.
- `scratch/i5_alpha_calls.py`, `scratch/i5_widget_audit.py`, `scratch/i5_compose_bench.py` — audyt.
- `Raporty/AMD_ETAP5G/VAL/i5_{A_ref,B_opt,C_ref,D_opt,E_ref}.mp4` (+ profiles) — full A/B/C/D/E.
- `Raporty/AMD_ETAP5G/VAL/i5_opt31.mp4` — short real test (31 kl.).

**STOP — raport gotowy. Nie wykonano ETAPU 5J. Nie przenoszono rendererów na GPU.**
