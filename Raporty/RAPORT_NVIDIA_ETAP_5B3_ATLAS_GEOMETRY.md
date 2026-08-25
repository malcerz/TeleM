# TeleM — NVIDIA ETAP 5B.3: HUD Atlas Geometry Audit

Data audytu: 2026-08-20  
Status: **AUDYT ZAKOŃCZONY — bez zmian produkcyjnych**

## A. Aktualny layout

Materiał reprodukcyjny:

- `Video/GX030120.MP4`
- `Video/Poranna_jazda_na_rowerze.fit`
- aktualny `def_layout.json`
- canvas HUD: `1920×1080`
- analizowane klatki: `0, 540, 1350, 2700, 4050, 4860, 5399` (`0%, 10%, 25%, 50%, 75%, 90%, 100%`)

Aktywnych jest 12 wskaźników. Precompute zachował historię obu wykresów:

- `fit_cadence_text`: `1672` punktów
- `fit_heart_rate_text`: `1672` punktów

Aktualny kod dokładnie odtwarza:

```text
global bbox: 1920×1080 / 100.0%
current atlas: 1828×978 / 86.216%
mode: FULL_FRAME, ponieważ 86.216% > 70%
```

## B–D. Per-indicator declared/actual bbox i waste

`declared bbox` poniżej oznacza geometrię używaną przez aktualny planner atlasu. `actual alpha bbox` jest unionem alpha z siedmiu punktów pomiarowych. Dla `track_map` render aktualny zwrócił brak obrazu; nie traktuję tego automatycznie jako dowodu, że mapa jest logicznie wyłączona.

| Key | Form | Declared bbox | Actual alpha union | Declared area | Alpha area | Waste |
|---|---|---:|---:|---:|---:|---:|
| `time_block` | text | `(11,14,424,169)` | `(31,34,56,57)` | 71,656 | 3,192 | 95.5% |
| `fit_cadence_text` | chart | `(45,748,676,332)` | `(92,790,577,229)` | 224,432 | 132,133 | 41.1% |
| `fit_enhanced_speed_text` | gauge | `(742,786,384,294)` | `(786,830,284,182)` | 112,896 | 51,688 | 54.2% |
| `fit_heart_rate_text` | chart | `(1191,749,676,331)` | `(1239,791,576,260)` | 223,756 | 149,760 | 33.1% |
| `fit_temperature_text` | text | `(1630,403,290,141)` | `(1650,422,97,15)` | 40,890 | 1,455 | 96.4% |
| `iso_text` | text | `(13,430,364,141)` | `(33,450,50,13)` | 51,324 | 650 | 98.7% |
| `exposure_text` | text | `(12,473,364,141)` | `(32,493,49,14)` | 51,324 | 686 | 98.7% |
| `temp_text` | text | `(12,514,364,141)` | `(32,534,60,13)` | 51,324 | 780 | 98.5% |
| `track_map` | map | `(1467,119,446,244)` | none observed | 108,824 | 0 observed | 100% observed |
| `fit_battery_text` | text | `(1630,448,290,141)` | none | 40,890 | 0 | 100% |
| `fit_battery_pct_text` | text | `(942,124,364,141)` | none | 51,324 | 0 | 100% |
| `fit_solar_pct_text` | text | `(940,66,364,141)` | none | 51,324 | 0 | 100% |

Największe declared/alpha waste mają małe text indicators. Ich planner geometry rezerwuje minimum około `12% canvas width` oraz szerokie marginesy, podczas gdy raster glyphów ma szerokość około `49–97 px`.

## E. Phantom bbox

Potwierdzone phantom candidates:

- `fit_battery_text`
- `fit_battery_pct_text`
- `fit_solar_pct_text`

Są `enabled=True`, ale FIT nie zawiera odpowiednich pól battery/solar, a w całym siedmiopunktowym audycie nie powstał żaden alpha pixel. Nie zostały usunięte produkcyjnie.

`track_map` ma dostępne dane (`1641` punktów GPS i `current_position ≈ 0.5001`), ale aktualny renderer zwrócił `None` dla testu diagnostycznego. Klasyfikacja: **RENDER_NOT_OBSERVED / wymaga osobnego audytu mapy**, nie potwierdzony phantom logiczny.

Usunięcie wyłącznie potwierdzonych phantom bboxów nie zmieniło wyniku atlasu 3-regionowego: nadal `1828×978`. Oznacza to, że główny wzrost wynika z układu pozostałych dużych prostokątów i limitu regionów, nie z samych battery/solar.

## F. Global bbox edge attribution

Globalny bbox `1920×1080` powstaje w starszej, bardziej konserwatywnej funkcji `get_layout_hud_bbox()`:

```text
LEFT EDGE:   time_block, iso_text, exposure_text, temp_text
TOP EDGE:    time_block
RIGHT EDGE:  fit_heart_rate_text, fit_temperature_text, track_map, fit_battery_text
BOTTOM EDGE: fit_cadence_text, fit_enhanced_speed_text, fit_heart_rate_text
```

W szczególności `time_block` przy pozycji blisko lewego/górnego brzegu oraz bottom charts powodują pełną wysokość/szerokość globalnego bboxa.

## G. Natural clusters

Dla aktualnego planner geometry po ograniczeniu do 3 regionów otrzymano:

```text
Cluster 0: fit_heart_rate_text + fit_cadence_text + fit_enhanced_speed_text
           bbox=(44,748,1824,332), area=605,568

Cluster 1: time_block + iso_text + exposure_text + temp_text
           bbox=(10,14,426,642), area=273,492

Cluster 2: fit_battery_pct_text + fit_solar_pct_text + track_map
           + fit_temperature_text + fit_battery_text
           bbox=(940,66,980,524), area=513,520
```

Najważniejsza obserwacja: dolny klaster ma szerokość `1824 px`, mimo że widoczny alpha jest znacznie bardziej zwarty. Następnie shelf packing układa trzy regiony w dwóch wierszach, co daje wysokość `978 px`.

## H. Merge history

Merge score w aktualnym kodzie to `merged_area - area_a - area_b`. Dla nakładających się bboxów wynik może być ujemny; jest to wynik signed, nie „ujemne marnotrawstwo”.

| Merge | Bbox merged | Area merged | Score |
|---|---:|---:|---:|
| `exposure_text + temp_text` | `(12,473,364,182)` | 66,248 | -36,400 |
| `iso_text + previous` | `(12,430,365,225)` | 82,125 | -35,447 |
| `fit_battery_pct_text + fit_solar_pct_text` | `(940,66,366,199)` | 72,834 | -29,814 |
| `fit_temperature_text + fit_battery_text` | `(1630,403,290,186)` | 53,940 | -27,840 |
| `fit_cadence_text + fit_enhanced_speed_text` | `(45,748,1081,332)` | 358,892 | 21,564 |
| `fit_heart_rate_text + bottom previous` | `(45,748,1822,332)` | 604,904 | 22,256 |
| `track_map + temp/battery` | `(1467,119,453,470)` | 212,910 | 50,146 |
| `time_block + left previous` | `(11,14,424,641)` | 271,784 | 118,003 |
| `upper-right groups` | `(940,66,980,523)` | 512,540 | **226,796** |

Największy pojedynczy merge według aktualnego score to merge dwóch prawych grup. Jednak powierzchnię końcową determinuje przede wszystkim kombinacja: szeroki dolny klaster `1824×332` + shelf packing + limit 3 regionów.

## I–J. Current final regions i packing efficiency

Aktualny zestaw produkcyjny dla `MAX_HUD_REGIONS=3`:

| Region | Source bbox | Atlas position |
|---:|---:|---:|
| 0 | `(44,748,1824,332)` | `(0,0,1824,332)` |
| 1 | `(10,14,426,642)` | `(0,336,426,642)` |
| 2 | `(940,66,980,524)` | `(430,336,980,524)` |

```text
sum(region_area) = 1,392,580 px
atlas_area        = 1,787,784 px
transparent_waste =   395,204 px
packing_efficiency = 77.9%
```

Diagnostyczny vertical-shelf packing dla tych samych trzech regionów dał `2254×860 = 1,938,440 px`, czyli więcej niż aktualny horizontal shelf (`1,787,784 px`). Aktualny horizontal shelf jest więc lepszym wariantem dla tego zestawu.

## K. Padding audit

Zidentyfikowane koszty geometryczne:

- indicator/form margins w plannerze:
  - text: około `±20 px` plus minimum text width/height;
  - chart/map: `+60/+50` do wymiaru bazowego oraz około `±20 px`;
  - gauge: promień `size×1.35` oraz dodatkowe `±10 px`;
  - time: dodatkowy obszar zależny od `20% canvas width` i `12% canvas height`;
- stroke/shadow: realny alpha jest mniejszy od widget bbox; nie zmieniano rendererów;
- region inter-padding: `4 px`;
- even alignment: może dodać `1 px` po prawej/dole.

Diagnostycznie, przy tym samym merge i `region padding=0`:

```text
current padding: 1828×978 = 1,787,784 px = 86.22%
zero padding:    1824×974 = 1,776,576 px = 85.68%
delta:                         11,208 px = 0.63% canvas
```

Padding atlasu nie jest przyczyną 86.2%; jego wpływ jest mały. Największy koszt jest w declared indicator geometry i wymuszonych merge’ach.

## L. MAX_HUD_REGIONS 1–6

| MAX | Regions | Atlas | Area | MB/frame | Sum region area | Efficiency |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 1914×1066 | 98.40% | 7.78 | 2,036,060 | 99.8% |
| 2 | 2 | 1914×978 | 90.27% | 7.14 | 1,831,788 | 97.9% |
| 3 | 3 | 1828×978 | 86.22% | 6.82 | 1,392,580 | 77.9% |
| 4 | 4 | 1828×978 | 86.22% | 6.82 | 1,166,548 | 65.3% |
| 5 | 5 | 1828×808 | 71.23% | 5.63 | 1,048,192 | 71.0% |
| 6 | 6 | 1916×582 | 53.78% | 4.25 | 998,632 | 89.6% |

`MAX=4` nie zmniejsza atlasu: region bottom nadal ma `1824 px` szerokości i shelf layout nadal ma `978 px` wysokości. `MAX=5` jest blisko, ale nadal przekracza próg `70%`. `MAX=6` jest pierwszym wariantem current declared geometry poniżej progu.

## M. NO-OP CUDA benchmark

Benchmark diagnostyczny:

- ten sam `GX030120.MP4`;
- 5400 klatek na przebieg;
- NVDEC → `scale_cuda` → `split/crop/scale/format/hwupload_cuda` → `overlay_cuda` → HEVC NVENC → null;
- transparentny atlas lavfi;
- bez Pillow, telemetry i realnego HUD;
- 3 przebiegi na wariant, raportowana mediana;
- FFmpeg `8.1.1`, RTX 5070 Ti, driver `610.62`.

| Wariant | Atlas | Median FPS | Median elapsed | Avg SM | Avg NVENC | Avg NVDEC |
|---|---:|---:|---:|---:|---:|---:|
| FULL_FRAME | 1920×1080 | 237.56 | 22.73 s | 30.6% | 38.6% | 47.1% |
| 3 regions | 1828×978 | 263.68 | 20.48 s | 58.9% | 49.0% | 69.6% |
| 4 regions | 1828×978 | 276.02 | 19.56 s | 64.2% | 50.1% | 80.1% |
| 5 regions | 1828×808 | 278.36 | 19.40 s | 61.2% | 52.1% | 76.8% |

W tym benchmarku dodatkowe regiony nie obniżyły throughputu, ponieważ warianty 4/5 mają tę samą lub mniejszą ilość transportowanych pikseli. Nie należy z tego wyciągać wniosku, że koszt pojedynczego operatora CUDA jest zerowy. Jest to benchmark end-to-end GPU filter graph, a nie izolowany koszt jednego operatora.

## N. Scenariusze atlasu

| Wariant | Regions | Atlas | Area | MB/frame | Redukcja względem 7.91 MB |
|---|---:|---:|---:|---:|---:|
| A. Current | 3 | 1828×978 | 86.22% | 6.82 | 13.78% |
| B. Precise alpha union, diagnostic | 3 | 1896×514 | 47.00% | 3.72 | 53.00% |
| C. Confirmed battery/solar phantom removal | 3 | 1828×978 | 86.22% | 6.82 | 13.78% |
| C2. Exclude all not-observed alpha, diagnostic | 3 | 1828×978 | 86.22% | 6.82 | 13.78% |
| D. 4 regions | 4 | 1828×978 | 86.22% | 6.82 | 13.78% |
| E. 5 regions | 5 | 1828×808 | 71.23% | 5.63 | 28.77% |
| F. 6 regions, current declared geometry | 6 | 1916×582 | 53.78% | 4.25 | 46.22% |

Wariant B jest wyłącznie diagnostyczny. Union alpha z siedmiu klatek nie jest jeszcze bezpiecznym declared bboxem produkcyjnym, szczególnie dla zmiennych tekstów i mapy.

## O. Rekomendacja

### Dlaczego atlas dla GX030120 osiąga 86.2%?

Nie przez padding atlasu i nie przez telemetry. Przyczyną jest kombinacja:

1. planner używa konserwatywnych declared bboxów, szczególnie dla małych tekstów;
2. trzy duże dolne elementy (`fit_cadence_text`, `fit_heart_rate_text`, `fit_enhanced_speed_text`) po merge tworzą prawie pełnoszeroki region `1824×332`;
3. limit `MAX_HUD_REGIONS=3` wymusza dodatkowe merge prawej grupy i lewej grupy;
4. shelf packing układa bottom region oraz dwa regiony górne w sposób dający `1828×978`;
5. globalny bbox `1920×1080` jest dodatkowo zawyżany przez konserwatywną funkcję, ale to atlas, a nie global bbox, decyduje tu o fallbacku.

### Który element/merge powoduje największy wzrost?

Największy merge score ma połączenie prawych grup (`226,796 px` signed merge score). Największym wymiarowym ograniczeniem jest jednak bottom cluster `1824×332`, który wymusza szerokość całego atlasu. Największe per-indicator waste mają `iso_text`, `exposure_text`, `temp_text`, `fit_temperature_text` oraz `time_block`.

### Jaki jest najmniejszy bezpieczny atlas?

Na podstawie aktualnej declared geometry i bez zmiany rendererów najmniejszy zmierzony wariant zachowujący wszystkie declared bboxy to:

```text
MAX=6: 1916×582, 53.78%, 4.25 MB/frame
```

`47.00%` z alpha union jest mniejszym wariantem diagnostycznym, ale nie jest jeszcze bezpieczną rekomendacją produkcyjną.

### Ile regionów daje najlepszy kompromis?

W tym konkretnym NO-OP benchmarku najlepszy zmierzony kompromis z badanych wariantów to **5 regionów** pod względem mediany GPU (`278.36 FPS`) przy `71.23%` atlasu. Jeśli kryterium transportu musi pozostać poniżej progu `70%`, pierwszy wariant spełniający ten warunek to **6 regionów**.

Nie zmieniono produkcyjnego `MAX_HUD_REGIONS=3`.

### Następny pojedynczy etap implementacyjny

Najpierw należy wykonać osobny, ograniczony etap implementacyjny dotyczący **precise declared bbox dla małych text indicators i potwierdzonych phantom bboxów**, z testem alpha/pixel parity. Dopiero po tej zmianie należy ponownie zmierzyć naturalne klastry i zdecydować, czy zmiana limitu regionów jest potrzebna.

Nie implementowano tej rekomendacji w ETAPIE 5B.3.

## Artefakty audytu

- `scratch/audit_etap5b3_geometry.py`
- `scratch/benchmark_etap5b3_cuda.py`
- `scratch/etap5b3_geometry/geometry_audit.json`
- `scratch/etap5b3_geometry/cuda_benchmark.json`
- `scratch/etap5b3_geometry/cuda_full_frame.json`
- `scratch/etap5b3_geometry/GX030120_atlas_geometry_audit.png`

Żaden plik produkcyjnego pipeline’u NVIDIA, rendererów, telemetry, NVENC/NVDEC ani progów wyboru trybu nie został zmieniony.
