# TeleM — NVIDIA ETAP 5E.6: Internal Chart Composite + Dynamic Layer Cache

Status: wdrożono po spełnieniu pixel-parity i kryterium wydajności. Dalsza optymalizacja zatrzymana.

## A. Internal composite profile

Profil wykonano na 1000 renderach każdego chartu. Najważniejsze fazy przed zmianą:

| Faza | Cadence avg / median / p95 ms | HR avg / median / p95 ms |
|---|---:|---:|
| `graph.history_chart_total` | 0.321 / 0.224 / 0.621 | 0.539 / 0.476 / 0.834 |
| `prefix_static_build` | 0.433 / 0.432 / 0.446 | 0.437 / 0.434 / 0.453 |
| `background_and_chart_composite` | 0.555 / 0.562 / 0.601 | 0.544 / 0.549 / 0.596 |
| `current_cursor` | 0.056 / 0.055 / 0.062 | 0.055 / 0.054 / 0.063 |
| `dynamic_labels` | 0.121 / 0.124 / 0.160 | 0.136 / 0.132 / 0.167 |
| `prefix.average` | — | 0.282 / 0.280 / 0.296 |
| `prefix.image_copy` | 0.068 / 0.091 / 0.106 | 0.055 / 0.027 / 0.099 |

Największy koszt wewnętrznego compositingu stanowiły operacje Pillow na całym dynamicznym obszarze: czyszczenie bufora, masked-paste prefixu oraz ponowne kopiowanie obrazu. HR dodatkowo wykonywał rysowanie linii average na każdej klatce.

## B. HR average cache feasibility

Bezpośrednie `ImageDraw.line(..., alpha=220)` i transparentna warstwa nakładana przez `alpha_composite` nie są pixel-identical: alpha-composite wykonuje blend, podczas gdy bieżący renderer zachowuje semantykę bezpośredniego zapisu Pillow.

Wariant transparent-layer + `alpha_composite` został odrzucony. Zastosowano dokładną maskę `L` i `ImageDraw.bitmap`, która zachowuje replacement semantics bieżącego `ImageDraw.line`.

Cache key obejmuje token historii, visible index, geometrię, zakres osi i styl. Cache jest worker-local i ograniczony do 256 warstw. Dla pełnych 5400 klatek:

- HR average: 5231 hits, 168 misses, hit rate 96.89%
- cadence average: nieaktywne w aktualnym layoucie (`show_average=false`)

## C. Current-label cache

Transparentny RGBA tile nakładany przez `alpha_composite` nie zachowuje parity z bezpośrednim `ImageDraw.text` na antialiased edges. Zamiast tego cache przechowuje dwa maski `L`:

1. stroke mask,
2. fill mask.

Są nakładane kolejno przez `ImageDraw.bitmap`, co zachowuje dokładny bbox, baseline, stroke i alpha replacement semantics.

Klucz zawiera finalny formatted string, font/path/size, stroke, fill, typ i anchor/style. Cache jest ograniczony do 128 pozycji.

## D. Prefix ROI composite

Źródłowa warstwa prefixu ma `576×230 = 132480 px`. Statyczny alpha-bbox osi/background geometry wynosi w aktualnym materiale około `555×194 = 107670 px`, czyli około 81.3% pełnej powierzchni.

Wykonano porównanie 2000 transferów:

- pełne czyszczenie + pełny masked-paste: avg 0.427 ms, median 0.424 ms, p95 0.442 ms;
- czyszczenie i masked-paste tylko cached ROI: avg 0.364 ms, median 0.361 ms, p95 0.379 ms.

Parity ROI względem pełnej bieżącej operacji: `max_diff=0`, `different_pixels=0`.

Nie użyto `getbbox()` per frame. Bbox jest wyprowadzany raz ze statycznej geometrii cache i ograniczony cache’em. Nie użyto plain paste.

## E. Buffer reuse

Zachowano worker-local reusable prefix buffer. Bufor jest deterministycznie czyszczony przed każdą klatką, ale tylko w statycznie potwierdzonym ROI. `final_static.copy()` nadal izoluje wynik zwracany do caller’a i nie zależy od kolejności klatek.

Nie wdrażano niebezpiecznego aliasowania bufora wynikowego ani odtwarzania zależnego od poprzedniej klatki.

## F. Dirty RGB investigation

Wcześniejszy audyt 5E.5 wykazał 53–54 piksele RGB pod `alpha=0` w gotowych rasterach chartów. Są one naturalnym skutkiem budowy RGBA przez Pillow, a ich usunięcie wymagałoby dodatkowego przebiegu.

Nie dodano cleanup pass, nie czyszczono RGB produkcyjnie i nie użyto tego problemu do wymuszenia plain paste.

## G. Implemented optimization

Zmieniono wyłącznie wewnętrzny renderer chartu:

- cache worker-local masek average per visible index;
- cache worker-local masek current-value label;
- dokładne nakładanie masek przez `ImageDraw.bitmap`;
- statyczny alpha-bbox ROI dla prefix buffer;
- ograniczone rozmiary cache.

Nie zmieniono: prefix semantics, Model A, cadence zero, `None`, gap segmentation, HR average meaning, cursor position, gauge, preview, Direct-Region, atlas planner, telemetry ani konfiguracji workerów/NVIDIA.

## H. Cache hit rates — 5400 klatek

| Cache | Hits | Misses | Hit rate |
|---|---:|---:|---:|
| HR average layer | 5231 | 168 | 96.89% |
| Cadence label | 5366 | 34 | 99.37% |
| HR label | 5386 | 14 | 99.74% |
| Cursor sprite | nie użyto osobnego cache | — | — |

Cursor pozostał dynamiczny względem exact current time.

## I. Pixel parity

Porównano cache OFF vs ON dla cadence i HR na checkpointach `0, 540, 1350, 2700, 4050, 4860, 5399`. Wszystkie local rasters:

`max_diff=0`, `different_pixels=0`.

Finalny Direct-Region atlas dla tych samych checkpointów również:

`max_diff=0`, `different_pixels=0`.

Test dodatkowy obejmował cadence `0`, `None`, długą lukę oraz kilka kolejnych klatek tego samego HR average. Nie wykryto zmiany semantyki ani wyglądu.

## J. Microbenchmark — 2000 rzeczywistych renderów

Wartości `avg / median / p95`, ms:

| Component | Before | After | Redukcja avg |
|---|---:|---:|---:|
| cadence local | 0.729 / 0.727 / 0.916 | 0.540 / 0.525 / 0.691 | 26.0% |
| HR local | 0.721 / 0.704 / 0.869 | 0.543 / 0.519 / 0.704 | 24.7% |
| cadence labels | 0.121 / 0.124 / 0.160 | 0.021 / 0.010 / 0.025 | 83.0% |
| HR labels | 0.136 / 0.132 / 0.167 | 0.017 / 0.010 / 0.015 | 87.2% |
| HR average phase | 0.282 / 0.280 / 0.296 | 0.180 / 0.010 / 0.383 | 36.0% avg |
| prefix ROI transfer | 0.427 / 0.424 / 0.442 | 0.364 / 0.361 / 0.379 | 14.7% |

Zysk local chartu przekracza wymagane 15% dla obu chartów.

## K. Worker profiler

Nowy pełny ranking worker-like, 300 klatek:

| Indicator | avg / median / p95 ms |
|---|---:|
| `fit_heart_rate_text` | 1.366 / 1.319 / 1.986 |
| `fit_cadence_text` | 1.315 / 1.280 / 1.781 |
| `time_block` | 0.818 / 1.199 / 1.354 |
| `track_map` | 0.615 / 0.520 / 0.716 |
| `fit_enhanced_speed_text` gauge | 0.429 / 0.396 / 0.555 |
| `iso_text` | 0.237 / 0.234 / 0.342 |

External worker-like compose: avg 6.237 ms, median 6.057 ms, p95 7.629 ms.

## L. Production benchmark

Wykonano 3 pełne eksporty aktualnego materiału z preview ON, Direct-Region, Multi-Region Atlas, 5 regionami, workers=4 i `MAX_IN_FLIGHT=8`.

| Run | FRAME_PIPELINE | REAL_EXPORT | Preview |
|---:|---:|---:|---:|
| 1 | 224.0 FPS | 209.2 FPS | 4.18 FPS |
| 2 | 228.4 FPS | 215.8 FPS | 4.31 FPS |
| 3 | 219.4 FPS | 207.3 FPS | 4.15 FPS |
| Median | **224.0 FPS** | **209.2 FPS** | **4.18 FPS** |

Produkcja pozostała blisko baseline’u 228.1 / 213.9 FPS. Producer nadal raportuje `DIRECT_REGION`, `MULTI_REGION_ATLAS`, 5 regionów, atlas `1900×762`.

## M. New bottleneck i odpowiedzi końcowe

1. Około 0.6 ms internal composite kosztowały przede wszystkim pełne czyszczenie/masked-paste prefixu oraz kopiowanie dynamicznego chart buffer; HR dodatkowo rysował average na każdej klatce.
2. HR average layer udało się bezpiecznie cache’ować jako dokładną maskę `ImageDraw.bitmap`; transparentny tile + `alpha_composite` został odrzucony z powodu różnic alpha semantics.
3. Current-label cache zachował pixel parity: `max_diff=0`, `different_pixels=0`.
4. Udało się zmniejszyć operację prefixu do statycznego ROI; parity wynosi 0/0, bez `getbbox()` per frame.
5. Po 5E.6: cadence około 0.540 ms, HR około 0.543 ms w 2000-render microbenchmarku.
6. Worker-like total compose wyniósł medianę około 6.057 ms; chart totals: cadence 1.315 ms, HR 1.366 ms.
7. Produkcyjny `FRAME_PIPELINE` wyniósł medianę **224.0 FPS**; `REAL_EXPORT` **209.2 FPS**.
8. Chart nadal jest największym pojedynczym kosztem CPU, szczególnie HR. Nie rozpoczynam jednak kolejnego etapu ani optymalizacji gauge.

Zmiany zapisano w aktualnym repozytorium, a ten etap zostaje zakończony.
