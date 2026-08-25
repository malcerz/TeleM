# TeleM — AMD ETAP 5C

Status: **PASS**

Zakres ograniczono do wnętrza `track_map`. Resolution-independent viewport z PRECHECK, telemetry ETAP 5B, ogólny HUD composite oraz cały GPU pipeline pozostały bez zmian.

## CORRECTED-MAP BASELINE

Oficjalny BEFORE został wykonany w nowym, pełnym 1131-frame real GUI production run z `AMD_OVERLAY_PROFILE=OFF`, native profiling OFF i diagnostics OFF:

- wall-clock: **100.643 s**
- TRUE FPS: **11.238**
- compose_overlay: AVG **61.798 ms**, Median 48.586 ms, P95 121.973 ms, P99 162.613 ms
- track_map z osobnego pełnego profiling run: AVG **25.094 ms**, Median 22.624 ms, P95 37.091 ms, P99 50.919 ms

Profilowany run nie został użyty jako baseline FPS.

## MAP PIPELINE BEFORE

`cached grid 1792×1792 (tiles + route)`
→ `pełne Image.copy() 1792×1792`
→ `marker w globalnych współrzędnych gridu`
→ `crop 692×692`
→ `resize 692×692 → 691×691`
→ `alpha_composite do HUD`

Route był już częścią cached grid i był rysowany tylko przy przebudowie gridu — w pełnym runie `route_polyline` miał 1 call. Największym zbędnym kosztem była pełna kopia cache przed cropem.

## MAP PIPELINE AFTER

`immutable cached grid 1792×1792 (tiles + route)`
→ `crop/copy tylko 692×692`
→ `marker w lokalnych współrzędnych cropu`
→ `resize 692×692 → 691×691`
→ `ten sam alpha_composite do HUD`

Współrzędne markera są przeliczane dokładnie jako:

`marker grid x/y - crop x/y = marker local x/y`.

Całkowitoliczbowe współrzędne cropu zachowują identyczną rasteryzację starego draw-then-crop. Cached grid nigdy nie jest modyfikowany przez marker.

## MEMORY

| Metryka | BEFORE | AFTER |
|---|---:|---:|
| Full cached-grid copy calls/frame | 1 | 0 |
| Pełna kopiowana powierzchnia cache | 3,211,264 px | 0 px |
| Region kopiowany cache→working | 3,211,264 px | 478,864 px |
| Region kopiowany cache→working RGBA | 12.250 MiB | 1.827 MiB |
| Redukcja transferu cache→working | — | **85.088%** |
| Łączne kopie full-copy + crop | 14.077 MiB | 1.827 MiB |
| Redukcja wszystkich kopii tej części | — | **87.023%** |
| Dynamic working image | 1792×1792, następnie 692×692 | wyłącznie 692×692 |

Grid `1792×1792` nadal istnieje jako persistent immutable cache. Usunięto jego per-frame kopię, nie sam cache.

## TIMINGS

Wartości pochodzą z dwóch pełnych 1131-frame overlay-profile runs.

| Stage | BEFORE AVG / Med / P95 / P99 | AFTER AVG / Med / P95 / P99 |
|---|---|---|
| position lookup | 0.015 / 0.014 / 0.022 / 0.041 ms | 0.014 / 0.013 / 0.022 / 0.034 ms |
| cached background handling | 3.114 / 2.692 / 3.658 / 8.642 ms | 0.112 / 0.002 / 0.003 / 0.006 ms |
| crop | 0.578 / 0.543 / 0.756 / 1.390 ms | 0.559 / 0.529 / 0.701 / 1.102 ms |
| marker | 0.068 / 0.061 / 0.095 / 0.201 ms | 0.048 / 0.044 / 0.063 / 0.116 ms |
| final 692→691 resize, Pillow inclusive | 28.147 / 25.299 / 51.748 / 62.431 ms | 26.202 / 24.683 / 31.498 / 56.324 ms |
| final map→HUD composite | 4.719 / 4.366 / 5.858 / 15.074 ms | 4.413 / 4.218 / 4.929 / 10.508 ms |
| track_map render | 20.237 / 18.080 / 32.112 / 43.068 ms | 15.323 / 14.317 / 19.668 / 31.395 ms |
| **track_map TOTAL** | **25.094 / 22.624 / 37.091 / 50.919 ms** | **19.880 / 18.709 / 29.687 / 38.210 ms** |

Pillow profiler rejestruje dwie zagnieżdżone operacje podczas jednego resize LANCZOS, dlatego wiersz resize jest wartością inclusive i nie sumuje się arytmetycznie z `track_map render`. Algorytm resize nie został zmieniony. Miarodajna oszczędność całego `track_map TOTAL` wynosi **5.214 ms/frame (20.778%)**.

Izolowany runner map-widget zmierzył:

- BEFORE AVG 18.910 ms, Median 17.706 ms, P95 29.394 ms, P99 43.347 ms
- AFTER AVG 15.434 ms, Median 14.452 ms, P95 23.386 ms, P99 33.003 ms
- oszczędność AVG: 3.476 ms/frame

## PIXEL TEST

- frames compared: **1131**
- mismatching frames: **0**
- MAE: **0.0**
- MAX: **0**
- P95/P99 dla frames 30/300/900: **0/0**
- raw RGBA SHA-256 każdego widgetu BEFORE/AFTER: **identyczny**
- finalny MP4 SHA-256 BEFORE/AFTER: **identyczny**

SHA-256 obu MP4:

`e500111095c66d33415f58db7b93255cc050de8a134075c8581190571f78bcbe`

## EDGE CASES

Kontrolowane testy porównują stary full-copy algorithm z nowym regional-crop algorithm byte-for-byte dla:

- początku i końca trasy,
- pozycji przed/po zakresem danych,
- środka trasy,
- przejść route przez lewą/prawą/górną/dolną krawędź viewportu,
- rozmiarów 173, 346 i 692,
- ponownego renderowania wcześniejszej pozycji po zmianie markera.

Wszystkie testy są pixel-identical. Cached route/background pozostaje niezmieniony między klatkami.

## PARITY

Plan PRECHECK BEFORE i AFTER jest identyczny:

- Preview 960: effective zoom 14, logical/working 173×173
- 1920: effective zoom 15, working 346×346
- Export 4K: effective zoom 16, logical 173×173, working 692×692, final 691×691

- Frame 30 bounds: **PASS**
- Frame 300 bounds: **PASS**
- Frame 900 bounds: **PASS**
- Marker: **PASS**
- Route: **PASS**
- Preview vs Export: **PASS**

Geografia, crop coordinates, marker source coordinates i końcowy resize nie zostały zmienione.

## FINAL REAL GUI EXPORT

- frames: **1131/1131**
- decoded / D3D surfaces / VP / GPU HUD / AMF submitted / AMF output / muxed: **1131/1131**
- AMF INPUT_FULL / retries / dropped / ignored: **0/0/0/0**
- FIT: **PASS**
- GPMF: **PASS**
- Date/time: **PASS**
- other HUD: **PASS**
- Color: **PASS**
- Audio: **PASS**
- audio elementary stream SHA-256 BEFORE/AFTER: identyczny `549c551024c0171d679cc8adb6ce35e6530291f75df485b51dfeee7a3e72ec55`
- GPU pipeline: **bez zmian**
- CPU base upload/readback: nadal **0**
- pełny test suite: **195 passed, 17 skipped**

## PERFORMANCE

| Production run | Wall-clock | TRUE FPS |
|---|---:|---:|
| Corrected-map BEFORE | 100.643 s | 11.238 |
| ETAP 5C AFTER | 79.294 s | 14.263 |

- obserwowany gain: **26.924%**
- wall-clock reduction: **21.349 s**
- compose_overlay AVG: **61.798 → 46.256 ms**

Pełne runy obejmują zmienność świeżego procesu i istniejącego background tile precache. Dlatego przyczynowy zysk samego kodu mapy należy oceniać przede wszystkim przez pełne profile (`track_map TOTAL −5.214 ms/frame`) i izolowany runner (`−3.476 ms/frame`), a nie przypisywać całych 21.349 s wyłącznie jednej instrukcji copy.

## ODPOWIEDZI WPROST

1. **Co powodowało największy koszt mapy?** Per-frame `Image.copy()` niemutowalnego gridu `1792×1792`, zanim znany już crop `692×692` został wycięty. Route była prawidłowo cache'owana.
2. **Czy pełna kopia 1792×1792 została usunięta?** Tak, z regularnej ścieżki per-frame całkowicie.
3. **Ile MB/frame kopiuje teraz mapa?** `1.827 MiB/frame` z cache do working crop zamiast `12.250 MiB/frame`; sama pełna kopia wynosi 0.
4. **Ile kosztuje track_map po zmianie?** AVG `19.880 ms/frame`, Median 18.709 ms, P95 29.687 ms, P99 38.210 ms.
5. **Czy wszystkie 1131 map widgets są pixel-identical?** Tak — 0 mismatches, MAE 0, MAX 0.
6. **Czy Preview↔Export parity nadal działa?** Tak; zoom 14/15/16 i bounds PRECHECK są zachowane.
7. **Jaki jest TRUE FPS?** `14.263 FPS` w produkcyjnym profiling-OFF runie.
8. **Jaki jest obecnie największy CPU bottleneck?** Nadal `track_map TOTAL` (~19.88 ms), głównie niezmieniony resize i finalny composite; następne są wykresy cadence (~9.44 ms) i HR (~7.77 ms).
9. **Czy można przejść do ETAP 5D — wykresy?** Tak. ETAP 5C spełnia correctness, memory i performance criteria.

## ARTEFAKTY

- `Raporty/AMD_ETAP5C/baseline_corrected_map_1131.mp4(.amd_profile.json)`
- `Raporty/AMD_ETAP5C/baseline_corrected_map_profile_1131.mp4(.amd_profile.json)`
- `Raporty/AMD_ETAP5C/after_profile_1131.mp4(.amd_profile.json)`
- `Raporty/AMD_ETAP5C/after_production_1131.mp4(.amd_profile.json)`
- `Raporty/AMD_ETAP5C/map_widget_before.json`
- `Raporty/AMD_ETAP5C/map_widget_after.json`
- `Raporty/AMD_ETAP5C/map_widget_pixel_comparison.json`

ETAP 5D nie został rozpoczęty.
