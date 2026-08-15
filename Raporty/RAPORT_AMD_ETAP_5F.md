# TeleM — AMD ETAP 5F — track_map final 692→691 resize

Status: **NO SAFE OPTIMIZATION** (audyt przyczynowy + pełna weryfikacja kandydatów; brak zmiany produkcyjnej)

Wynik 5F: LANCZOS 692→691 **nie może zostać usunięty ani przyspieszony pixel-exact** w obecnej ścieżce CPU. Jego realny koszt to **~14.2 ms/frame** (dominujący element mapy i ~37% `compose_overlay`). Wszystkie szybsze warianty zmieniają piksele → odrzucone. Kod produkcyjny **nie został zmieniony** (tylko analiza).

## WHY 692 / WHY 691 — źródła wartości i rounding

| Wartość | Źródło | Obliczenie | Rounding |
|---|---:|---|---|
| **691** (final widget) | `size_px = s(18.0, canvas_w)` w `dispatcher.py` | `round((18.0/100) × 3840)` = `round(691.2)` | Python `round` (banker's) → **691** |
| **960** (reference width) | `MAP_ZOOM_REFERENCE_CANVAS_WIDTH` (`indicators/moving_map.py`) | stała: logiczna szerokość canvasu Preview | — |
| **4.0** (canvas_scale) | `_map_render_plan`: `canvas_w / 960` | `3840/960` | dokładnie 4.0 |
| **2** (zoom_offset) | `floor(log2(4.0))` | — | floor → **2** |
| **16** (effective_zoom) | `configured_zoom 14 + zoom_offset 2` | — | — |
| **4** (density) | `2^zoom_offset` | `2^2` | dokładnie 4 |
| **173** (logical_size) | `round(output_size / canvas_scale)` | `round(691/4.0)` = `round(172.75)` | round → **173** (kwantyzacja 5C PRECHECK: Preview i Export dzielą ten sam całkowitoliczbowy logical pixel grid) |
| **692** (working_size) | `round(logical_size × density)` | `round(173 × 4)` | **692** |
| **691** (output_size) | layout `size=18%` | `round(0.18×3840)` | **691** |
| **0.99855** (resize scale) | `output_size / working_size` | `691/692` | LANCZOS |

**Dlaczego 692 a finalny widget 691:** dwie **niezależne** kwantyzacje:
1. `691 = round(18% × 3840)` — rozmiar widgetu z layoutu (względem szerokości canvasu),
2. `692 = round(round(691/4) × 4) = round(173 × 4)` — rozmiar roboczy z kwantyzacji logicznego viewportu (173 px, celowo całkowitego dla parzystości Preview↔Export) × gęstość kafelków (4 dla 4K).

Ponieważ `173 × 4 = 692 ≠ 691`, zostaje 1 px rozbieżności; **końcowy LANCZOS 692→691 (skala 0.9986) godzi kwantyzowany obraz roboczy z rozmiarem layoutu**. To zamierzone zachowanie 5C PRECHECK („gotowe 692×692 jest skalowane o jeden piksel do rzeczywistego widgetu 4K 691×691”), a nie błąd.

## REAL RESIZE COST (izolowany, profiler OFF — bez podwójnego księgowania)

`scratch/etap5f_resize_bench.py`, realny crop mapy 692×692:

| Metryka | AVG | Median | P95 | P99 |
|---|---:|---:|---:|---:|
| `Image.resize((691,691), LANCZOS)` (90 klatek, realny crop) | 14.225 ms | 14.100 ms | 14.981 ms | 18.361 ms |
| `render()` = crop 692 + marker (90 klatek) | 1.356 ms | 0.555 ms | 0.712 ms | 9.856 ms |
| render + resize razem | 15.581 ms | 14.695 ms | 15.646 ms | 30.423 ms |
| syntetyczny opaque 692→691 LANCZOS (kontrola) | 14.269 ms | 14.104 ms | 14.646 ms | 16.842 ms |

- Sam resize = **~91%** ścieżki render+resize mapy; w pełnym `track_map TOTAL` (profiler OFF ~16 ms) to **~89%**.
- Syntetyczny opaque daje ten sam koszt → to czysto **koszt C-kernelu LANCZOS w Pillow** (~7 tapów na oś, ~49 próbek/px, RGBA), a nie tiles/marker/overhead.
- Profil `pillow.resize` z ETAPU 5C/D (~26 ms „inkluzywnie”) był **podwójnie księgowany** przez zagnieżdżone hooki profilerów; realny pojedynczy koszt to **~14.2 ms**.

## CANDIDATES (1131 klatek, pixel-exact gate)

| Wariant | Czas AVG | Mismatches | MAE | MAX | P95_MAX | P99_MAX | Decyzja |
|---|---:|---:|---:|---:|---:|---:|---|
| **A. REFERENCE** 692→LANCZOS→691 | 15.581 ms | — (referencja) | — | — | — | — | — |
| **B. DIRECT 691** render w 691 (bez resize) | 0.829 ms (**18.8×**) | **1131/1131** | 9.063 | **255** | 247 | 255 | **REJECT** |
| **C. TRANSFORM (fractional LANCZOS)** | N/A | — | — | — | — | — | **REJECT** (Pillow `Image.transform` AFFINE nie wspiera LANCZOS — tylko NEAREST/BILINEAR/BICUBIC; BICUBIC zmienia piksele) |
| **D. CROP-CENTER 691** z 692 (bez resamplingu) | 0.554 ms (**28×**) | **1131/1131** | 8.955 | **244** | 242 | 242 | **REJECT** |

Powód odrzucenia B i D: render/crop w 691 próbkuje **inne** kafelki (inny całkowitoliczbowy offset cropu, `int(scx−691/2)` vs `int(scx−692/2)`), inny viewport geograficzny (172.75 vs 173 logical px — brak całkowitego poziomu zoomu dającego 691 przy tych samych bounds), inna pozycja/rasteryzacja markera i route oraz **brak resamplingu LANCZOS**. Każda z tych różnic osobno łamie pixel-exact.

## ALLOCATIONS / COPIES per frame

BEFORE (= AFTER — brak bezpiecznej zmiany):

| Operacja | Alokacja | Rozmiar | Konieczna? |
|---|---:|---:|---|
| `img.crop((x1,y1,x2,y2))` (working 692) | nowy `Image` 692×692 RGBA | 1 915 456 B ≈ 1.83 MB | TAK — marker dynamiczny wymaga zapisywalnej kopii (cached grid immutable, ETAP 5C) |
| `map_img.resize((691,691), LANCZOS)` | nowy `Image` 691×691 RGBA | 1 909 924 B ≈ 1.82 MB | TAK — LANCZOS nie może być in-place |
| final composite (5E paste fast-path) | zapis do persistent canvas (bez nowego pełnego `Image`) | 0 (region) | TAK |
| **Razem** | **2 alokacje** ≈ **3.65 MB/frame** | | brak zbędnego intermediate |

Źródłowy bufor 692 **nie jest kopiowany dodatkowo** (crop jest właśnie buforem roboczym). Redukcja alokacji „wokół resize” nie jest możliwa bez zmiany wyniku: marker musi być rysowany na 692 i poddany LANCZOS (rysowanie markera po resize dałoby ostry, inny pikselowo marker — REJECT), a crop 692 jest wymagany dla markera.

## MAP PIXEL TEST

| Porównanie | Frames | Mismatching | MAE | MAX |
|---|---:|---:|---:|---:|
| REFERENCE vs B (direct 691) | 1131 | **1131** | 9.06 | 255 |
| REFERENCE vs D (crop 691) | 1131 | **1131** | 8.96 | 244 |

Żaden kandydat nie przechodzi (wymagane 0/0/0). Referencja względem siebie: identyczna.

## PARITY

Nie zmieniono żadnego kodu mapy w 5F. Parity Preview↔Export, bounds, marker, route pozostają takie jak w zwalidowanym ETAPIE 5C/5E (finalny MP4 5E bit-for-bit == 5D == 5C): **PASS** (dziedziczone, bez zmian).

## PERFORMANCE

5F = **NO SAFE OPTIMIZATION** → brak modyfikacji produkcyjnej → production baseline bez zmian:

| Metryka | ETAP 5E | ETAP 5F |
|---|---:|---:|
| TRUE FPS | 15.781 | **bez zmian (15.781)** — brak zmiany kodu |
| compose_overlay AVG | 38.571 ms | **bez zmian (38.571 ms)** |
| track_map (render+resize) | ~16 ms | bez zmian (resize ~14.2 ms nieredukowalne pixel-exact) |

Nie wykonano nowego eksportu produkcyjnego, bo nie ma zmiany do pomiaru — stan jest dokładnie zwalidowanym stanem 5E (bez dotknięcia w 5F).

## ODPOWIEDZI WPROST

1. **Dlaczego powstaje 692, a finalny widget ma 691?** `691 = round(18%×3840)` (rozmiar layoutu); `692 = round(round(691/4)×4) = round(173×4)` (całkowitoliczbowa kwantyzacja logicznego viewportu 173 z 5C PRECHECK × gęstość 4 dla 4K). Dwie niezależne kwantyzacje dają 1 px różnicy; LANCZOS 0.9986 godzi je.
2. **Ile naprawdę kosztuje sam LANCZOS 692→691?** **~14.2 ms/frame AVG** (realne pojedyncze wywołanie, profiler OFF; Median 14.1, P95 15.0, P99 18.4). To ~89–91% kosztu ścieżki mapy i ~37% `compose_overlay`. Czysty koszt C-kernelu LANCZOS (nie tiles/marker/overhead — syntetyczny opaque daje ten sam wynik).
3. **Czy resize można całkowicie usunąć pixel-exact?** **NIE.** Direct 691 (B) i crop 691 (D) zmieniają sampling, bounds (172.75 vs 173 logical), marker, route i rasteryzację (MAX 244–255, MAE ~9, 1131/1131 mismatches). Transform LANCZOS (C) jest niemożliwy w Pillow (AFFINE nie wspiera LANCZOS). Brak całkowitego zoomu dającego 691 przy tych samych bounds.
4. **Który wariant był najszybszy pixel-exact?** **Żaden** — każdy szybszy wariant zmienia piksele. Jedynym pixel-exact jest obecny LANCZOS (15.58 ms render+resize).
5. **Czy wszystkie 1131 map widgets są identyczne?** Względem referencji — każdy kandydat ma **1131/1131 mismatches** (nie są identyczne). Referencja sama ze sobą — tak.
6. **Jaki jest TRUE FPS?** Bez zmian: **15.781** (5E). 5F nie zmienia kodu, więc nie ma nowego eksportu do pomiaru.
7. **Co jest teraz największym bottleneckiem?** **Sam LANCZOS resize mapy (~14.2 ms = ~37% compose_overlay, ~89% track_map)**. Dalej: `PIL/buffer preparation` (~12 ms), telemetry (~6.4 ms).
8. **Czy CPU Pillow map renderer osiągnął praktyczną granicę?** **TAK dla pixel-exact CPU.** Crop (~1.4 ms) jest wymagany dla markera; LANCZOS (~14 ms) to inherentny koszt ~7-tapowego resamplingu w Pillow — żadna ścieżka Pillow nie produkuje identycznych pikseli szybciej.
9. **Czy następny etap powinien przenieść część mapy/resize na GPU?** **TAK — rekomendowane.** D3D11 texture map renderer renderujący wprost w docelowej rozdzielczości (bez CPU LANCZOS) to naturalny kandydat na ~10–14 ms zysku. UWAGA: GPU LANCZOS/sampler **nie jest bit-identyczny** z Pillow LANCZOS, więc nowa ścieżka GPU będzie miała inny (prawdopodobnie równie dobry lub lepszy) wygląd — wymaga osobnego etapu z własnymi kryteriami A/B (visual match lub akceptacja nowego wyglądu), a nie pixel-exact względem obecnego CPU outputu. Ewentualnie CPU fallback dla pixel-exact pozostaje dostępny.

## ZMIANY W KODZIE

- **Brak zmian produkcyjnych** (git: tylko nowe skrypty analityczne `scratch/etap5f_resize_bench.py`, `scratch/etap5f_candidates.py`).
- Zachowane: 5B (telemetry), 5C (map grid/crop/parity), 5D (chart cache), 5E (composite_final + track_map paste fast-path), dirty upload, D3D11VA/P010/VP/NV12 compute/AMF, NVIDIA/Intel.

## ARTEFAKTY

- `scratch/etap5f_resize_bench.py` — izolowany pomiar kosztu LANCZOS 692→691,
- `scratch/etap5f_candidates.py` — pełne porównanie kandydatów A/B/D na 1131 klatkach.

ETAP 5F kończy się wynikiem **NO SAFE OPTIMIZATION** (dozwolonym przez specyfikację). **Nie rozpoczęto kolejnego etapu.**
