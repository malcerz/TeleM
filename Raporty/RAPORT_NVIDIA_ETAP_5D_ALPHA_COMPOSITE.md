# TeleM — NVIDIA ETAP 5D: Alpha Composite Fast Path

## A. Current composite call graph

Aktualna ścieżka NVIDIA po 5C:

```text
render_frame_shm_job
→ render_overlay_frame
→ compose_overlay(target_image=atlas, coordinate_origin, render_keys)
→ rotated_paste
→ composite_final
```

W aktualnym repozytorium `rotated_paste.py` już zawiera domyślny `OPTIMIZED` fast path: transparentny bbox, crop actual alpha bbox, plain `paste` dla udowodnionego transparentnego celu oraz fallback do `alpha_composite`. W ETAPIE 5D nie zmieniono tego kodu, ponieważ świeży A/B nie wykazał bezpiecznego zysku netto.

## B. Per-indicator composite cost

Świeży profiler: 300 steady-state frames, Direct-Region, atlas `1900×762`.

| Indicator | Form | Composite method | Raster | Calls/frame | ms/frame |
|---|---|---|---:|---:|---:|
| `fit_cadence_text` | chart | alpha/crop fallback | 584×264 | 1 | 0.552 |
| `fit_heart_rate_text` | chart | alpha/crop fallback | 584×264 | 1 | 0.384 |
| `fit_enhanced_speed_text` | gauge | alpha/crop fallback | 324×324 | 1 | 0.168 |
| `time_block` | time | optimized paste/crop | 56×57 | 1 | 0.110 |
| `fit_temperature_text` | text | optimized paste | 97×15 | 1 | 0.076 |
| `iso_text` | text | optimized paste | 44×13 | 1 | 0.053 |
| `exposure_text` | text | optimized paste | 49×14 | 1 | 0.050 |
| `temp_text` | text | optimized paste | 60×13 | 1 | 0.048 |

Łączny pomiar `pillow.alpha_composite`: około `1.75–1.79 ms/frame`, 8 wywołań/frame. Alpha composite pochodzi praktycznie z chartów i gauge; tekst korzysta z tańszych ścieżek, gdy warunki są dowiedzione.

## C. Overlap analysis

Na rzeczywistych widgetach z klatki 2700 sprawdzono aktywne piksele alpha w globalnych bboxach. Nie znaleziono żadnej pary indicatorów z aktywnym overlapem. Przezroczyste marginesy nie były traktowane jako overlap.

## D. Tested compositing methods

Przetestowano:

1. `alpha_composite` — referencja;
2. `paste(src, mask=src)`;
3. actual alpha bbox crop + `alpha_composite`;
4. plain `paste` wyłącznie dla rasterów, dla których cel jest transparentny i warunek jest dowiedziony.

`paste(mask=src)` odrzucono jako ogólny fast path. Dla rzeczywistych tekstów i chartów dawał różnice RGBA. Aktualny plain `paste` pozostaje selektywny i nie jest używany dla przezroczystych widgetów bez dowodu.

## E. Pixel semantics

Przykładowe wyniki microbenchmarku 1000 powtórzeń na rzeczywistych rozmiarach:

| Form | Alpha avg µs | Paste-mask avg µs | Crop-alpha avg µs | Paste-mask parity |
|---|---:|---:|---:|---|
| text `fit_temperature` | 10.6 | 6.9 | 17.4 | FAIL, max_diff=64 |
| text `iso` | 8.7 | 4.7 | 14.2 | FAIL, max_diff=64 |
| chart cadence | 365.3 | 492.1 | 459.5 | FAIL, max_diff=77 |
| chart HR | 294.7 | 487.1 | 375.8 | FAIL, max_diff=77 |
| gauge | 79.6 | 336.8 | 65.3 | FAIL, max_diff=64 |

Crop-alpha miał `max_diff=0`, `different_pixels=0` w testowanych rasterach, ale nie daje zysku dla tekstu i aktualna ścieżka już wybiera go selektywnie.

## F. Microbenchmark

Microbenchmark obejmował minimum 1000 powtórzeń dla każdego aktywnego typu: chart, gauge, text i time_block. Pomiary obejmowały rzeczywiste rastry wygenerowane przez aktualne renderery, bez obrazów 10×10.

## G. Implemented fast paths

W ETAPIE 5D nie wdrożono nowego fast path. Aktualny kod już posiada:

- no-op dla pustego alpha bbox;
- crop actual alpha bbox;
- plain `paste` tylko dla dowiedzionego transparentnego celu;
- fallback do dokładnego `alpha_composite` przy overlapie lub niepewnej alpha semantics.

Testowany cache decyzji transparentności dawał około `7.835 → 7.669 ms` worker-like, czyli około 2.1%, ale wynik pozostawał wolniejszy/niepewniejszy względem referencji w pojedynczym A/B i komplikowałby cache dla dynamicznych widgetów. Został wycofany.

## H. Pixel parity

Nie zmieniono producer code, więc zachowano parity Direct-Region z ETAPU 5C. Dla 7 punktów timeline oraz ROT180: `max_diff=0`, `different_pixels=0`.

## I. Worker profiler before/after

| Phase | BEFORE 5D avg ms | AFTER 5D avg ms | Reduction |
|---|---:|---:|---:|
| worker-like total | 7.835 | 7.926 | brak poprawy w świeżym pomiarze |
| alpha_composite | 1.748 | 1.787 | wynik pomiarowy, bez zmiany kodu |
| paste | 0.097 | 0.098 | bez zmiany |
| crop | 0.190 | 0.190 | bez zmiany |

Różnica mieści się w szumie pomiarowym. Nie ma dowodu na poprawę całego workera.

## J. Per-indicator profiler

Renderowanie chartów pozostaje największym kosztem poza samym compositingiem:

| Indicator | Render ms | Composite before | Composite after | Total after |
|---|---:|---:|---:|---:|
| cadence chart | 0.518 | 0.552 | 0.552 | około 1.07 |
| HR chart | 0.438 | 0.384 | 0.384 | około 0.82 |
| gauge | 0.554 | 0.168 | 0.168 | około 0.72 |
| time_block | 0.040 | 0.110 | 0.110 | około 0.15 |
| fit temperature | 0.022 | 0.076 | 0.076 | około 0.10 |

## K. Production benchmark 3×

Wykonano 3 pełne eksporty na aktualnym, niezmienionym producerze Direct-Region:

| Run | FRAME_PIPELINE | FPS | PRODUCTION_TOTAL | REAL_EXPORT_FPS | write avg | write p95 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 26.774 s | 201.7 | 28.384 s | 190.2 | 2.68 ms | 6.08 ms |
| 2 | 26.330 s | 205.1 | 27.705 s | 194.9 | 2.75 ms | 5.92 ms |
| 3 | 26.503 s | 203.8 | 27.857 s | 193.8 | 2.64 ms | 5.68 ms |
| **median** | **26.503 s** | **203.8 FPS** | **27.857 s** | **193.8 FPS** | **2.68 ms** | **5.92 ms** |

Atlas pozostał `1900×762`, MAX4, GRID16, `69.821%`. Direct-Region nadal loguje się jako aktywny.

## L. Complexity vs benefit

`paste(mask=src)` nie spełnia pixel parity. Crop-alpha jest poprawny, ale aktualny kod już go używa tam, gdzie ma sens. Dalsze cache’owanie analizy transparentności daje tylko około 2% worker-like i nie daje stabilnego zysku end-to-end.

Zgodnie z kryterium ETAPU 5D nie dodano agresywnej optymalizacji dla 1–2%.

## M. New bottleneck

Największym hotspotem pozostaje renderowanie chartów, następnie gauge. Sam alpha compositing chartów/gauge jest konieczny dla poprawnej półprzezroczystej semantyki. Następny sensowny kierunek to osobny audyt rendererów chart/gauge, nie dalsza zmiana compositingu.

## Zmienione pliki

W ETAPIE 5D nie zmieniono plików produkcyjnych. Utworzono wyłącznie:

- `Raporty/RAPORT_NVIDIA_ETAP_5D_ALPHA_COMPOSITE.md`;
- diagnostyczne skrypty i wyniki w `scratch/`.

## Konkluzja

Alpha/compositing kosztował około `1.75 ms/frame` przed i około `1.79 ms/frame` w świeżym pomiarze po — bez zmiany produkcyjnej. Fast path korzystają z niego tekst, time_block i bezpieczne przypadki transparentnego celu; chart/gauge pozostają przy dokładnej semantyce alpha. Wynik RGBA pozostaje bit-identyczny. Nowy rzeczywisty medianowy `FRAME_PIPELINE` wynosi `203.8 FPS`. Dalsza optymalizacja compositingu nie ma obecnie uzasadnionego zysku; następny hotspot to rendering chartów/gauge.

