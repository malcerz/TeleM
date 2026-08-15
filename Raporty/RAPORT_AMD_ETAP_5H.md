# RAPORT AMD — ETAP 5H: Optymalizacja HUD buffer preparation / regional CPU bridge

**Status: ⚠️ PUNKT BEZPIECZNEGO FLOORU OSIĄGNIĘTY** — audyt + implementacja
`AMD_HUD_BUFFER_MODE=REFERENCE|OPTIMIZED`. OPTIMIZED jest **byte-identical**,
ale **performance-neutral** (różnica w granicach szumu sesji). Nie zastosowano
żadnych unsafe hacków. **Brak zmian w compose/GPU/telemetry. STOP — nie wykonano 5I.**

> Główny wniosek: ścieżka Pillow→backing jest już na bezpiecznym minimum
> **(3 kopie/rect)**, ponieważ Pillow nie udostępnia żadnego zero-copy odczytu
> bufora (potwierdzone: `__array_interface__['data']` zwraca kopię bytes, nie
> wskaźnik). Dalsza redukcja wymaga zmian ZABRONIONYCH w 5H (np. render HUD
> bezpośrednio do bufora numpy = zmiana compose_overlay, albo nowe natywne API
> per-rect uploadu = zmiana pipeline'u).

---

## CURRENT PIPELINE (po 5G, GPU_HUD DIRTY)

```
composed_img (persistent Pillow RGBA 3840x2160, mutowany w miejscu)
  → dla każdego dirty rect (5 rects, ~8.03 MiB/frame):
      REFERENCE: crop (kopiuje region) → np.asarray (kopiuje znów, przez
                 __array_interface__ bytes) → np.copyto (strided write)
      = 3 kopie/rect
  → hud_backing (persistent ctypes 15360 B/row) → telem_amd_update_hud_regions
  → native: UpdateSubresource per rect (box) → GPU HUD texture
```

Odpowiedzi na 10 punktów audytu:
1. persistent Pillow: `_THREAD_CANVAS.cache` w `compositor.py` (`reuse_canvas=True`).
2. dirty rects: `_dirty_rects_from_bboxes` (previous+current bboxy, pad 40px, `_coalesce_dirty_rects`).
3. regiony z Pillow: `Image.crop(rect)`.
4. crop: TAK (kopiuje region do nowego Image).
5. tobytes: TAK (REFERENCE nie używa; np.asarray robi to wewnętrznie przez bytes).
6. NumPy: TAK (`np.asarray` + `np.copyto`).
7. ctypes.memmove: REFERENCE nie używa (używa `np.copyto`).
8. kopie/rect: **3** (crop + intermediate + strided write).
9. backing: `hud_backing = (ctypes.c_uint8 * (W*H*4))()` — persistent.
10. stride do native: `video_width*4` = **15360 B/row** (tight, brak paddingu).

## REFERENCE (kopia chain)

| Etap | med (ms/rect) | kopie |
|---|---|---|
| crop | 0.50 | 1 |
| np.asarray | 1.12–1.20 | 1 (przez bytes z `__array_interface__`) |
| np.copyto | 0.29 | 1 (strided write) |
| **razem** | **~1.9–2.0 / rect** | **3** |
| **5 rects / frame** | **~9.5 ms (microbench) / 11–13 ms (produkcja)** | **~22.4 MiB traffic (3×7.46)** |

## WAŻNE ODKRYCIE — PULAPKA STRIDE (sekcja 11)

`ctypes.memmove(backing + y*stride + x*4, data, rw*rh*4)` (flat) jest **BŁĘDNY**:
backing ma stride 15360 B, a rect ma tylko rw*4 B szerokości — flat copy przesuwa
każdy wiersz po pierwszym w niepoprawne miejsce. **Złapane przez test byte-exact**
(mismatch max=255). Poprawne: `np.copyto` (strided, jedna operacja) albo per-row
`memmove` (wolniejsze: 12.4 ms vs 9.5 ms).

## MERGE AUDIT (sekcja 6/7)

| Wariant | rects | logical | kopie(3×) | czas (microbench) |
|---|---|---|---|---|
| CURRENT | 5 | 7.46 MiB | 22.4 MiB | 9.60 ms |
| MERGE-OVERLAP | 5 (brak overlapów) | 7.46 MiB | 22.4 MiB | — |
| MERGE-COST→4 | 4 | 7.95 MiB | 23.9 MiB | 9.21 ms (gorzej) |
| MERGE-COST→3 | 3 | 8.53 MiB | 25.6 MiB | 9.63 ms (gorzej) |

**Merge NIE jest opłacalny** (dodane bajty przewyższają oszczędność call overhead).
Zgodnie z regułą „Nie wdrażaj merge, jeżeli zwiększa całkowity koszt" — **nie wdrożono**.

## OPTIMIZED (wdrożone, eksperymentalne)

`AMD_HUD_BUFFER_MODE=OPTIMIZED` = `crop → tobytes → np.frombuffer (view, zero-copy)
→ np.copyto`. Usuwa redundantną kopię numpy przez `__array_interface__` (bytes).
**Byte-identical** z REFERENCE (zweryfikowane: 20 realnych klatek + 15 adversarialnych
rectów, brak overrun). **Bezpieczne API** (żadnych wewnętrznych wskaźników Pillow).

REFERENCE pozostaje **domyślne** (brak zmiany zachowania produkcyjnego).

---

## MICROBENCH (1000 iter, realne dirty recty)

```
REFERENCE crop+asarray+copyto        med=9.60 ms
OPTIMIZED crop+tobytes+frombuffer+copyto  med=9.58 ms   (== REF)
OPTIMIZED per-row memmove            med=12.35 ms       (wolniej)
```

## PIXEL/BYTE TEST (sekcje 9/10)

| Test | Wynik |
|---|---|
| Real frames (300–319) | **20/20 identical** (backing byte-for-byte) |
| Adversarial rects (borders, corners, 1px, full, overlap, width 1/3/17/173/691/1160) | **identical + no overrun** |
| HUD buffer prep BEFORE→AFTER | 11.53 → 11.95 ms med (produkcja) — **bez redukcji** |
| Kopie/rect BEFORE→AFTER | 3 → 3 |

## SHORT REAL TEST (sekcja 21)

`h5_opt31.mp4`: 31/31 frames, D3D11VA, GPU MAP, OPTIMIZED. `HUD dirty extract`
med 8.52 ms. HUD+mapa obecne, brak green/magenta (0.000%). AMF drops 0. PASS.

## FULL A/B/C/D (sekcja 22, 1131 frames każdy, D3D11VA + GPU MAP, profiling/diag/readback OFF)

| Run | Tryb | TRUE FPS | wall | HUD buffer prep med | compose_overlay med |
|---|---|---|---|---|---|
| A | REFERENCE | 16.327 | 69.3 s | 11.14 ms | 25.17 ms |
| B | OPTIMIZED | 19.532 | 57.9 s | 10.87 ms | 24.15 ms |
| C | REFERENCE | 17.841 | 63.4 s | 11.92 ms | 25.53 ms |
| D | OPTIMIZED | 16.319 | 69.3 s | 13.02 ms | 27.94 ms |

```
REFERENCE MEDIAN:  17.084 FPS   (16.327, 17.841)
OPTIMIZED MEDIAN:  17.926 FPS   (19.532, 16.319)
GAIN:              +4.9 %  →  W GRANICACH SZUMU (rozrzut OPT 16.3–19.5)
```

HUD buffer prep: REF median 11.53 ms vs OPT median 11.95 ms — **nie spadł**
(różnica w granicach wariancji; oba tryby ~3 kopie).

## BOTTLENECKS AFTER 5H

1. **compose_overlay (Pillow HUD compose)** — med 24–28 ms produkcja (największy koszt).
2. **HUD buffer prep** — med 11–13 ms (bezpieczne minimum ~3 kopie/rect; wymaga
   zmiany architektury aby zejść niżej).
3. **HUD texture upload** — med 1.5–1.9 ms (native UpdateSubresource per rect).
4. **telemetry/frame_data** — med ~3–6 ms.
5. **map CPU praca** (crop+marker+tobytes+upload) — ~2–2.5 ms.

## ODPOWIEDZI WPROST

1. **Co powodowało 9.3 ms HUD buffer prep?** 3 kopie/rect × ~8 MiB/frame
   (Pillow crop + np.asarray przez `__array_interface__` (bytes) + np.copyto),
   plus alokacje obiektów per rect. Pillow nie udostępnia zero-copy odczytu.
2. **Ile kopii pikseli BEFORE?** **3/rect** (crop, intermediate, strided write).
3. **Ile kopii AFTER?** **3/rect** (crop, tobytes, copyto) — `frombuffer` to view (0 kopii).
4. **Ile MiB/frame usunięto?** **0** — traffic bez zmian (~22.4 MiB Python / frame
   w obu trybach; ~8.03 MiB logical dirty).
5. **Czy usunięto NumPy intermediate?** Nie w pełni — `np.frombuffer` (view) zastępuje
   `np.asarray`, ale copyto nadal potrzebne; usunięto tylko redundantną kopię numpy
   przez bytes. Nie wpłynęło to na czas.
6. **Czy dirty geometry się zmieniła?** Nie — 5 rects / ~8.03 MiB, te same co REFERENCE.
   Merge odrzucony (zwiększa koszt).
7. **Czy wszystkie bytes identyczne?** **Tak** — 20/20 realnych klatek + adversarialne
   recty byte-identical, brak overrun.
8. **Ile kosztuje teraz HUD buffer prep?** ~11–13 ms/frame (produkcja) — **bez redukcji**
   (bezpieczne minimum).
9. **Median TRUE FPS?** REFERENCE 17.084 / OPTIMIZED 17.926 (+4.9%, w granicach szumu).
10. **Największy bottleneck?** `compose_overlay` (Pillow, 24–28 ms) — to on tworzy CPU floor.
11. **Czy 5I powinien dotyczyć compose_overlay?** **Tak** — to największy realny koszt CPU.
    Dalsza redukcja HUD buffer prep poniżej ~11 ms wymagałaby zmiany architektury
    (render HUD do numpy-backed bufora = zmiana compose, albo natywne per-rect API),
    co wykracza poza dozwolony zakres 5H.

## KRYTERIA PASS (ocena)

| # | Kryterium | Wynik |
|---|---|---|
| 1 | renderery widgetów bez zmian | ✅ PASS |
| 2 | GPU map path bez zmian | ✅ PASS |
| 3 | dirty bytes byte-identical | ✅ PASS (20/20 + adversarial) |
| 4 | final HUD pixel-identical | ✅ PASS (byte-exact backing ⇒ identical) |
| 5 | brak unsafe Pillow internals | ✅ PASS (tylko crop/tobytes/frombuffer/copyto) |
| 6 | CPU memory traffic spadł | ❌ **NIE** (3 kopie/rect, floor) |
| 7 | HUD buffer prep timing spadł | ❌ **NIE** (11.53→11.95 med, w szumie) |
| 8 | full export 1131/1131 | ✅ PASS |
| 9 | AMF drops 0 | ✅ PASS |
| 10 | FPS nie regresuje | ✅ PASS (REFERENCE domyślne bez zmian) |

**Wniosek:** 5H dokumentuje, że HUD buffer preparation znajduje się na bezpiecznym
minimum przy aktualnych ograniczeniach. Wdrożono `AMD_HUD_BUFFER_MODE=REFERENCE` (domyślne,
bez zmian) + `OPTIMIZED` (byte-identical, performance-neutral, dostępne eksperymentalnie).
**5I powinien celować w `compose_overlay` (24–28 ms).**

## PLIKI / ARTEFAKTY

- `src/ffmpeg/amd_native_exporter.py` — `AMD_HUD_BUFFER_MODE`, `HUD dirty bbox/extract` timing.
- `scratch/h5_audit.py` — audyt + microbench (1000 iter, realne recty).
- `scratch/h5_correctness.py` — byte-exact (20 realnych + 15 adversarialnych rectów).
- `Raporty/AMD_ETAP5G/VAL/h5_{A_ref,B_opt,C_ref,D_opt}.mp4` (+ profiles) — A/B/C/D.
- `Raporty/AMD_ETAP5G/VAL/h5_opt31.mp4` — short real test (31 kl.).

**STOP — raport gotowy. Nie wykonano ETAPU 5I. Nie przenoszono rendererów na GPU.**
