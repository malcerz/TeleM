# RAPORT NVIDIA ETAP 5E.4 — Direct-to-Atlas Chart Rendering

Data: 2026-08-20  
Zakres: wyłącznie analiza i próba Direct-to-Atlas dla `fit_cadence_text` oraz
`fit_heart_rate_text`.

Nie zmieniono produkcyjnie correct-prefix math, Modelu A, alpha semantics,
gauge, preview, region plannera, MAX5/GRID16, workers/MAX_IN_FLIGHT,
FFmpeg/NVENC/NVDEC ani telemetry.

## A. Current local-raster cost

Aktualna ścieżka Direct Region kieruje kompozycję do atlasu, ale chart nadal
wykonuje `local chart RGBA → rotated_paste → alpha_composite/crop → atlas`.

Izolowany benchmark 1000 wywołań bez profilera:

| Seria | Local render avg | median | p95 |
|---|---:|---:|---:|
| cadence | 0,752 ms | 0,745 ms | 0,894 ms |
| HR | 0,878 ms | 0,876 ms | 0,973 ms |

Profil fazowy wskazał dodatkowo: prefix static assembly `0,416/0,440 ms`,
cursor `0,055/0,058 ms`, current label `0,235/0,293 ms` oraz local image
copy `0,105/0,098 ms` (cadence/HR). HR ma dodatkowo linię average około
`0,282 ms` w profilu z narzutem Pillow.

## B. Transfer/composite cost

Ten sam benchmark rozdzielił lokalny render od `rotated_paste`:

| Seria | Transfer avg | median | p95 |
|---|---:|---:|---:|
| cadence | 1,171 ms | 1,168 ms | 1,335 ms |
| HR | 1,136 ms | 1,145 ms | 1,286 ms |

| Seria | Render + transfer avg | median | p95 |
|---|---:|---:|---:|
| cadence | 1,923 ms | 1,927 ms | 2,160 ms |
| HR | 2,014 ms | 2,024 ms | 2,226 ms |

Suma cadence + HR wynosi około `3,936 ms avg` w izolowanym full path.
Profil Pillow wskazał w transferze m.in. `alpha_composite` około `0,616 ms`
cadence i `0,453 ms` HR oraz `paste` około `0,426/0,451 ms`. Te fazy zawierają
narzut instrumentacji.

## C. Overlap analysis

Cadence, gauge i HR są przydzielone do jednego szerokiego regionu atlasu, ale
ich konserwatywne bboxy renderowania są rozłączne i stałe przez timeline:

| Element | Bbox globalny |
|---|---|
| cadence | `x=92..676`, `y=796..1060` |
| gauge `fit_enhanced_speed_text` | `x=766..1090`, `y=814..1138` |
| HR | `x=1244..1828`, `y=796..1060` |

Nie ma overlapu cadence–gauge ani gauge–HR. Direct path mógłby zachować
z-order dla aktualnego layoutu, ale przyszły overlap wymagałby fallbacku.

## D. Alpha semantics

Przetestowano wariant zachowujący lokalny `bg_img`, ale wstawiający header,
background, cursor, dot i current label bezpośrednio do atlas ROI.

Finalny atlas nie był pixel-identyczny z referencją local-raster +
`rotated_paste`:

```text
max_diff = 255
different_pixels = 91..160 na checkpoint
```

Różnice występowały przy granicach cursor/label i w półprzezroczystych
antialiased pixels. Direct `ImageDraw` na większym atlasie nie jest
automatycznie równoważny rysowaniu na lokalnym transparentnym RGBA, a potem
alpha compositingowi.

## E. Direct-to-Atlas design

Prototyp miał kontrakt `target_image`, `target_origin`, `target_rotation`.
Lokalna geometria, Model A i prefix nie były zmieniane. Direct path był
ograniczony do rotacji `0°` i sprawdzał granice ROI.

Prototyp został całkowicie wycofany z kodu produkcyjnego, ponieważ nie spełnił
`max_diff=0`. Aktualnie nadal obowiązuje bezpieczna ścieżka local-raster.

## F. Hybrid path

Nie wdrożono hybrydy. Samo przeniesienie backgroundu bez lokalnej warstwy
dynamicznej nie zachowuje tego samego clippingu i alpha ordering dla cursor
oraz current label. ROI temporary layer wymagałby dalszej weryfikacji i nie
dał jeszcze zmierzonego, stabilnego zysku.

## G. Rotation/fallback

Prototyp był dozwolony wyłącznie dla `0°`; dla `90°`, `180°`, `270°` oraz
niepewnego ROI pozostawał local-raster fallback. Po wycofaniu prototypu
wszystkie rotacje korzystają wyłącznie z dotychczasowej ścieżki. NVIDIA ROT180
i transformacja atlasu nie zostały zmienione.

## H. Pixel parity

Referencją był aktualny renderer 5E.3. Sprawdzono atlas RGBA dla 0%, 10%,
25%, 50%, 75%, 90%, 100% oraz osobno cadence i HR.

Aktualna ścieżka local-raster pozostaje zgodna z wcześniejszym testem:

```text
max_diff = 0
different_pixels = 0
```

Prototyp Direct-to-Atlas miał `max_diff=255` i `different_pixels > 0`, więc
nie został wdrożony.

## I. Chart full-path benchmark

| Wariant | Cadence avg | HR avg | Razem avg |
|---|---:|---:|---:|
| 5E.3 local chart-only | 0,811 ms | 0,833 ms | 1,644 ms |
| 5E.4 local render + atlas transfer | 1,923 ms | 2,014 ms | 3,936 ms |
| 5E.4 direct/hybrid | odrzucony | odrzucony | parity failure |

Istotny koszt pozostaje w transferze lokalnego RGBA do atlasu, a nie w
bisect/X/Y prefixu.

## J. Worker profiler

Ponieważ Direct-to-Atlas nie został wdrożony, worker pozostaje na baseline
5E.3:

| Komponent | avg ms | median ms | p95 ms |
|---|---:|---:|---:|
| cadence total | 1,497 | 1,548 | 1,690 |
| HR total | 1,731 | 1,709 | 1,845 |
| cadence + HR | 3,228 | 3,256 | 3,534 |
| gauge | 0,383 | 0,381 | 0,473 |
| worker-like compose | 6,538 | 6,679 | 7,227 |

Gauge nie był zmieniany i pozostaje wyraźnie mniejszym kosztem niż chart.

## K. Production benchmark

Nie wykonano nowych trzech eksportów, ponieważ żadna zmiana 5E.4 nie została
wdrożona. Obowiązuje ostatni potwierdzony baseline 5E.3:

```text
FRAME_PIPELINE median = 228,1 FPS
REAL_EXPORT median    = 213,9 FPS
```

Direct Region, MULTI_REGION_ATLAS, MAX5, GRID16, preview ON, workers=4 i
MAX_IN_FLIGHT=8 pozostają bez zmian.

## L. New bottleneck

Najważniejszy pozostały koszt to transfer lokalnego chartu do atlasu:

```text
~1,17 ms cadence
~1,14 ms HR
```

Nie można go usunąć przez proste rysowanie bezpośrednio na atlasie, ponieważ
zmienia to alpha/clipping i łamie parity. Kolejny bezpieczny kierunek wymaga
pixel-exact ROI compositora albo zweryfikowanej warstwy hybrydowej; nie jest
implementowany w tym etapie.

## Odpowiedzi końcowe

1. Local raster kosztuje około `0,752 ms` cadence i `0,878 ms` HR; transfer do
   atlasu dodaje odpowiednio `1,171 ms` i `1,136 ms`.
2. Nie udało się wdrożyć rysowania chartu bezpośrednio do atlasu z zachowaniem
   parity.
3. Bezpieczny hybrid temporary layer nie został wdrożony.
4. Aktualna ścieżka produkcyjna pozostaje `max_diff=0`; prototyp miał
   `max_diff=255` i został odrzucony.
5. Produkcyjny chart full-path pozostaje bez zmian. Izolowany local render +
   transfer kosztuje około `3,936 ms avg` dla cadence+HR.
6. `FRAME_PIPELINE` nie został ponownie mierzony, bo nie wdrożono zmiany;
   obowiązuje mediana `228,1 FPS`.
7. Tak. Chart nadal jest większym celem niż gauge.

ETAP 5E.4 zakończony. Direct-to-Atlas nie został wdrożony z powodu braku
pixel parity. Dalsza optymalizacja zatrzymana.
