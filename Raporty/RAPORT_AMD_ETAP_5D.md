# TeleM — AMD ETAP 5D

Status: **PASS**  
Zakres: wyłącznie `fit_cadence_text` i `fit_heart_rate_text`; bez zmian mapy, telemetry, ogólnego compositingu HUD i pipeline'u GPU.

## Audyt i semantyka wykresów

Oba aktywne wykresy są typu **fixed-history + moving cursor**, nie moving-window:

- pełne listy cadence i heart rate powstają raz w `init_worker()` przez `build_chart_data()` i pozostają niezmienne przez eksport;
- osie, grid, etykiety osi, historyczna polilinia, fill, średnia (HR) i nagłówek nie zależą od numeru klatki;
- per-frame zmieniają się tylko indeks/pozycja kursora oraz sformatowana bieżąca wartość;
- `current_position` nadal jest liczony jako `frame_index / (total_frames - 1)`, a `current_index` nadal używa istniejącego `round()` i clamp.

Kolejność alpha BEFORE była istotna: kursor był rysowany na kopii chart-body, po czym całe RGBA było wklejane przez `paste(chart_img, mask=chart_img)`. Nowy kod zachowuje wynik tej operacji byte-for-byte, łącznie z wtórnym przeliczeniem alfy linii kursora i clippingiem kropki przy prawej krawędzi.

## Cache i invalidation

Nowy `FINAL_STATIC_CHART` zawiera:

- transparent background i border/dekoracje,
- axes/grid i etykiety osi,
- całą historyczną polilinię i fill,
- linię średniej, jeśli jest aktywna,
- statyczny header/label.

Klucz cache składa się z kompletnego klucza chart background i headera. Uwzględnia tożsamość i długość graph data, wymiary, min/max/range, line/fill/grid colors, line width, alpha, axes/grid, time/value labels, units, average, supersampling, font/font size oraz header, outline, text color i offsety. `indicator type` nie jest osobnym polem klucza, ponieważ jego jedyny wpływ — domyślny kolor — jest już zapisany jako rozstrzygnięty `line_color`; identyczne końcowe parametry mogą bezpiecznie współdzielić identyczną warstwę.

Konfiguracja i chart data są immutable w obrębie eksportu. Zmiana layoutu lub danych tworzy inny klucz; nie dodano globalnego systemu invalidacji. Profil pełnego eksportu potwierdził dokładnie **1 static build na cadence i 1 na HR**.

## CADENCE BEFORE

Pipeline:

`cached chart background → full chart-body copy → cursor → full header copy → large masked paste chart-body → current value → unchanged final HUD composite`

Static operations/frame:

- ponowne składanie statycznego chart-body do finalnego widgetu: 1;
- duże kopie: 2 (`1152×460` + `1160×511`);
- duży wewnętrzny masked paste: 1.

Dynamic operations/frame: cursor + current value.

| Etap | AVG ms | Median | P95 | P99 |
|---|---:|---:|---:|---:|
| history chart | 0.928 | 0.865 | 1.209 | 1.785 |
| cursor | 0.900 | 0.842 | 1.174 | 1.672 |
| static/final assembly | 3.335 | 2.952 | 4.390 | 11.281 |
| value label | 0.774 | 0.721 | 0.987 | 1.711 |
| render total | 5.327 | 4.815 | 7.051 | 14.891 |
| final HUD paste/composite | 3.938 | 3.755 | 4.604 | 6.678 |
| **indicator TOTAL** | **9.444** | **8.789** | **11.960** | **20.969** |

## CADENCE AFTER

Pipeline:

`build FINAL_STATIC_CHART once → one final-static copy/frame → exact legacy cursor → current value → unchanged final HUD composite`

Static operations/frame:

- static rebuild/assembly: **0** (1 build/export, około 3.129 ms jednorazowo);
- duże kopie: **1** (`1160×511`);
- duży wewnętrzny masked paste: **0**.

Dynamic operations/frame: one writable static copy + cursor + current value. Do zachowania starego clippingu kropka kursora używa małego lokalnego tile, nie chart-body.

| Etap | AVG ms | Median | P95 | P99 |
|---|---:|---:|---:|---:|
| static cache lookup/history geometry | 0.019 | 0.011 | 0.018 | 0.039 |
| cursor | 0.208 | 0.188 | 0.301 | 0.511 |
| static copy + cursor/assembly | 1.149 | 1.090 | 1.546 | 2.230 |
| value label | 0.901 | 0.747 | 1.315 | 3.105 |
| render total | 2.177 | 1.950 | 2.993 | 6.631 |
| final HUD paste/composite | 4.443 | 4.232 | 5.401 | 12.056 |
| **indicator TOTAL** | **6.797** | **6.352** | **8.510** | **16.472** |

Saving: **2.647 ms/frame** w indicator total; sam render spadł o **3.149 ms/frame**. Wzrost zmierzonego final HUD composite jest szumem/zmiennością poza zakresem 5D; jego kod nie został zmieniony.

## HEART RATE BEFORE / AFTER

Pipeline BEFORE i AFTER jest analogiczny do cadence. HR ma dodatkową statyczną linię średniej i ona również jest częścią `FINAL_STATIC_CHART`.

| Etap | BEFORE AVG | AFTER AVG | AFTER Median | AFTER P95 | AFTER P99 |
|---|---:|---:|---:|---:|---:|
| history chart / static lookup | 0.594 | 0.013 | 0.007 | 0.011 | 0.017 |
| cursor | 0.575 | 0.143 | 0.128 | 0.196 | 0.306 |
| static/final assembly | 2.637 | 0.754 | 0.688 | 0.989 | 1.404 |
| value label | 0.753 | 0.765 | 0.701 | 0.972 | 2.503 |
| render total | 4.195 | 1.592 | 1.449 | 2.038 | 5.934 |
| final HUD paste/composite | 3.415 | 3.564 | 3.238 | 4.459 | 10.993 |
| **indicator TOTAL** | **7.769** | **5.300** | **4.845** | **6.659** | **16.403** |

Static build: 1/export, około 2.743 ms jednorazowo.  
Saving: **2.469 ms/frame** w indicator total; sam render spadł o **2.604 ms/frame**.

## Memory / copy audit

Wymiary 4K dla obu widgetów: chart-body `1152×460`, final widget `1160×511`.

| Metryka / wykres | BEFORE | AFTER |
|---|---:|---:|
| large `Image.copy` calls/frame | 2 | 1 |
| copied pixels/frame (steady state) | 1,122,680 | 592,760 |
| copied RGBA MiB/frame | 4.283 | 2.261 |
| redukcja copied pixels | — | 47.20% |
| large internal assembly paste/frame | 1 | 0 |
| tiny cursor-tile paste/frame | 0 | 1 |
| unchanged final HUD composite/frame | 1 | 1 |

Usunięto kopię całego `1152×460` chart background oraz masked paste całego chart-body. Pozostaje jedna kopia finalnego statycznego widgetu, ponieważ dynamiczny cursor i value label muszą być narysowane na zapisywalnym obrazie.

## Pixel test

Porównano surowe RGBA, nie skompresowane MP4:

| Indicator | Frames | Mismatches | MAE | MAX |
|---|---:|---:|---:|---:|
| Cadence | 1131 | 0 | 0 | 0 |
| Heart rate | 1131 | 0 | 0 | 0 |
| **Łącznie** | **2262** | **0** | **0** | **0** |

Indeksy kursora dla 0/30/300/600/900/1130 są identyczne: `0/45/452/904/1356/1703`.

Kontrolowane testy objęły początek/koniec, minimum/maksimum, wartości powtarzalne, nagłą zmianę, brak kursora/missing display (`--`) i clipping prawej krawędzi. Semantyka interpolation/telemetry nie była zmieniana.

## Final regression

Pełny real GUI production export:

- source/decoded/D3D surfaces/VP/GPU HUD/AMF submitted/AMF output/muxed: **1131/1131**;
- AMF INPUT_FULL: 0; retries: 0; dropped: **0**;
- CPU raw base/upload/readback: nadal 0;
- finalny MP4 ETAP 5C SHA-256: `e500111095c66d33415f58db7b93255cc050de8a134075c8581190571f78bcbe`;
- finalny MP4 ETAP 5D SHA-256: `e500111095c66d33415f58db7b93255cc050de8a134075c8581190571f78bcbe`.

Identyczny hash całego MP4 potwierdza jednocześnie zgodność video/HUD/audio dla wszystkich klatek, nie tylko klatek kontrolnych.

| Kontrola | Wynik |
|---|---|
| Frame 30 | PASS |
| Frame 300 | PASS |
| Frame 900 | PASS |
| FIT | PASS |
| GPMF | PASS |
| Map / ETAP 5C parity | PASS |
| Date/time | PASS |
| Cadence | PASS |
| Heart rate | PASS |
| Speed / other HUD | PASS |
| Color | PASS |
| Audio | PASS |

Mapa i jej cache/zoom/crop nie zostały zmienione. Telemetry 5B, dirty regions, ogólny `alpha_composite`, D3D11VA/P010/VP/NV12 compute/AMF również nie zostały zmienione.

## Performance

Normal production, profiling OFF, diagnostics OFF:

| | ETAP 5C | ETAP 5D |
|---|---:|---:|
| wall-clock | 79.294 s | 73.323 s |
| TRUE FPS | 14.263 | **15.425** |
| compose_overlay AVG | 46.256 ms | **40.845 ms** |

Zysk TRUE FPS: **+8.14%**.  
Oszczędność compose_overlay: **5.410 ms/frame**.

Największym obecnym CPU bottleneckiem pozostaje zamrożony `track_map`: **20.212 ms/frame** w kontrolnym profilu 5D (około 19.88 ms w baseline 5C).

## Odpowiedzi wprost

1. Największym zbędnym kosztem były druga duża kopia chart-body/final widget oraz ponowne masked-paste statycznego chart-body w każdej klatce.
2. Cache'owany jest kompletny statyczny final chart: header, osie, grid, labels, pełna historia/fill i — dla HR — average line.
3. Per-frame renderowane są: jedna zapisywalna kopia final static chart, cursor/dot oraz bieżąca wartość; końcowy HUD composite pozostał bez zmian.
4. Cadence oszczędza **2.647 ms/frame** w pełnym koszcie indicatora (**3.149 ms/frame** w samym rendererze).
5. HR oszczędza **2.469 ms/frame** w pełnym koszcie indicatora (**2.604 ms/frame** w samym rendererze).
6. Tak — wszystkie **2262/2262** widgety są pixel-identical.
7. TRUE FPS = **15.425**.
8. Największym CPU bottleneckiem jest obecnie `track_map`, około **20.21 ms/frame**.
9. Tak — kryteria 5D są spełnione i technicznie można przejść do ETAPU 5E. ETAP 5E nie został rozpoczęty.

## Artefakty i testy

- `Raporty/AMD_ETAP5D/chart_widgets_before.json`
- `Raporty/AMD_ETAP5D/chart_widgets_after.json`
- `Raporty/AMD_ETAP5D/chart_widget_pixel_comparison.json`
- `Raporty/AMD_ETAP5D/after_profile_1131.mp4.amd_profile.json`
- `Raporty/AMD_ETAP5D/after_production_1131.mp4.amd_profile.json`
- PNG frames 0/30/300/600/900/1130 dla obu wykresów BEFORE/AFTER
- test suite: **198 passed, 17 skipped**

