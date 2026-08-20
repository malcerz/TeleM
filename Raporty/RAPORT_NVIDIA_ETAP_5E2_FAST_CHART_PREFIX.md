# RAPORT NVIDIA ETAP 5E.2 — Fast Prefix Chart Rendering

Data: 2026-08-20  
Zakres: wyłącznie `fit_cadence_text` i `fit_heart_rate_text`.

Nie zmieniano gauge, alpha compositing, preview, dynamic FIT discovery,
battery/solar, MAX5, GRID16, Direct-Region, atlasu, telemetry precompute,
SmartSync, workers/MAX_IN_FLIGHT ani FFmpeg/NVENC/NVDEC.

## A. Current 5E.1 cost breakdown

Świeży profil obejmował 1000 wywołań każdego wykresu.

| Phase | Cadence ms | HR ms | Total ms |
| --- | ---: | ---: | ---: |
| bisect/current index | 0.001 | 0.001 | 0.001 |
| segment selection | 0.001 | 0.001 | 0.003 |
| X mapping / point list | 0.049 | 0.052 | 0.101 |
| fill polygon | 0.121 | 0.065 | 0.187 |
| line drawing | 0.026 | 0.024 | 0.050 |
| image copy | 0.066 | 0.071 | 0.137 |
| prefix static assembly | 0.438 | 0.437 | 0.875 |
| cursor | 0.057 | 0.057 | 0.114 |
| current label | 0.124 | 0.140 | 0.264 |
| prefix average | 0.000 | 0.287 | 0.287 |

HR ma dodatkowo `show_average=True`, dlatego jego średnia jest osobnym
kosztem. Bisect i wybór segmentów są pomijalne.

## B. X-domain analysis

Obowiązuje Model A:

```text
activity_start → current_time = pełna szerokość wykresu
```

Przy `current=50%` punkt z połowy aktywności trafia na prawą krawędź
prefixu. W Modelu B ten sam punkt pozostałby w połowie szerokości. Crop/reveal
pełnego rastra nie może więc być pixel-identical. Model B zmieniałby semantykę
wizualną i nie został wdrożony.

## C. Tested fast-prefix strategies

Przetestowano:

1. cache pełnego rastra + crop/reveal — odrzucony, ponieważ Model A zmienia
   skalę X całego prefixu;
2. cached segment rasters w normalized coordinates + resize — odrzucony,
   ponieważ resize/interpolation nie daje gwarancji surowej zgodności RGBA;
3. precomputed elapsed seconds + cached Y + cached segment ranges — wdrożony;
4. cache sum/count dla średniej HR — wdrożony;
5. reuse czyszczonego bufora `header + prefix` — wdrożony.

## D. Rejected strategies and why

Nie wdrożono Modelu B, prostego maskowania ani skalowania gotowego rastra.
Każda z tych metod pokazuje punkty w stałych współrzędnych aktywności, a nie
w domenie `activity_start → current_time`.

Nie wdrożono NumPy/`array('f')` jako formatu dla Pillow. Pillow nadal wymaga
konwersji do sekwencji punktów dla `line`/`polygon`; dodatkowa konwersja nie
była uzasadniona zyskiem.

## E. Implemented optimization

W `src/indicators/chart_utils.py` cache przechowuje teraz wyrównane
timestampy, elapsed seconds, pełne punkty z gotowym Y, granice segmentów,
X bounds, cumulative sum/count oraz min/max dla `show_average`.

Per frame nie jest już wykonywane timezone normalization całej historii,
ponowne wyznaczanie segmentów, skanowanie historii do średniej ani ponowne
wyliczanie Y.

`_PREFIX_STATIC_BUFFER_CACHE` reuse’uje tylko wewnętrzny obraz bazowy.
Prostokąt wykresu jest w całości czyszczony przed każdym paste, a zwracany
obraz pozostaje osobną kopią. Nie ma zależności od kolejności klatek.

## F. Pixel parity

Correct-prefix reference z 5E.1 tworzy `ChartHistory` zawierający wyłącznie
próbki `timestamp <= current_time`. Nowy renderer porównano dla 0%, 10%, 25%,
50%, 75%, 90%, 100%, przed długą luką, wewnątrz luki i na pierwszym punkcie
po luce — osobno cadence i HR, z różnymi timestampami.

W każdym checkpointcie:

```text
max_diff = 0
different_pixels = 0
```

Przy 100% nowy wynik jest równoważny pełnej historii.

## G. Semantic tests

Zachowane i zweryfikowane: pierwszy sample pozostaje początkiem aktywności,
próbki przyszłe nie są rysowane, `cadence=0.0` pozostaje punktem, `None` i
długa luka dzielą segment, historia przed luką pozostaje po luce, brak sliding
window, a cadence i HR używają własnych timestampów.

Testy:

```text
32 passed in 2.81s
```

## H. Chart-only benchmark — 1000 wywołań

| Wariant | Chart | avg ms | median ms | p95 ms |
| --- | --- | ---: | ---: | ---: |
| naive correct-prefix | cadence | 2.069 | 1.645 | 3.562 |
| current 5E.1 optimized-prefix | cadence | 1.035* | 0.880* | 1.522* |
| new 5E.2 fast-prefix | cadence | 0.823 | 0.730 | 1.140 |
| naive correct-prefix | HR | 2.016 | 1.600 | 3.471 |
| current 5E.1 optimized-prefix | HR | 1.075* | 0.944* | 1.478* |
| new 5E.2 fast-prefix | HR | 0.842 | 0.776 | 1.061 |

`*` wartości 5E.1 pochodzą z benchmarku bazowego tego etapu.

Suma cadence+HR:

| Wariant | avg ms | median ms | p95 ms |
| --- | ---: | ---: | ---: |
| naive correct-prefix | 4.085 | 3.245 | 7.033 |
| current 5E.1 | 2.110 | 1.824 | 3.001 |
| new 5E.2 | **1.665** | **1.506** | **2.202** |

Nowy wariant redukuje koszt względem 5E.1 o około **21%** i spełnia próg
wdrożenia 20%.

## I. Worker profiler

Aktualny worker-like compose, 300 wywołań z obiema aktywnymi historiami:

```text
avg    5.530 ms
median 5.445 ms
p95    6.728 ms
```

Największe komponenty po zmianie to prefix static assembly, HR average line,
dynamic value label i cursor. Bisect i segment selection nie są hotspotami.

## J. Production benchmark

Po wdrożeniu 5E.2 wykonano trzy eksporty preview ON dla
`GX030120.MP4` + `Popoludniowa_jazda_na_rowerze_solar_battery.fit`.

Każdy eksport potwierdził `DIRECT_REGION`, `MULTI_REGION_ATLAS`, MAX5 / 5
regions, atlas `1900x762`, workers=4 i MAX_IN_FLIGHT=8.

| Run | FRAME_PIPELINE FPS | REAL_EXPORT FPS | preview FPS |
| ---: | ---: | ---: | ---: |
| 1 | 217.0 | 203.3 | 4.07 |
| 2 | 218.4 | 206.6 | 4.13 |
| 3 | 218.3 | 206.2 | 4.12 |
| **median** | **218.3** | **206.2** | **4.12** |

`ffmpeg_write`:

```text
run 1: avg 3.96 ms, p95 13.53 ms
run 2: avg 4.08 ms, p95 14.40 ms
run 3: avg 3.89 ms, p95 13.39 ms
median: avg 3.96 ms, p95 13.53 ms
```

Względem baseline’u `225.4 / 210.5 FPS` wynik jest niższy, ale mieści się
w obserwowanym szumie eksportu. Lokalna para GPMF/FIT ma nadal niespójne
absolutne timestampy; SmartSync nie był zmieniany.

## K. New bottleneck

Największym hotspotem jest składanie dynamicznego obrazu `header + prefix`,
a dla HR dodatkowo rysowanie linii średniej. Wąskie gardło nie leży już
w bisect, gap detection ani Y mapping.

## Odpowiedzi końcowe

1. Prosty crop/reveal pełnego chartu nie był możliwy, ponieważ Model A
   przeskalowuje cały prefix na pełną szerokość.
2. Tak. Obecna oś X wymaga przeskalowania całego widocznego prefixu przy
   zmianie current time.
3. Precompute/cache obejmuje elapsed seconds, timestampy, gotowe Y, segment
   ranges, X bounds, cumulative average sum/count oraz reuse bufora obrazu.
4. Po 5E.2 cadence+HR kosztują **1.665 ms avg**, **1.506 ms median**,
   **2.202 ms p95**.
5. Tak. Wynik jest bit-identyczny z correct-prefix reference 5E.1:
   `max_diff=0`, `different_pixels=0`.
6. Nowy median `FRAME_PIPELINE`: **218.3 FPS**.
7. Największym hotspotem jest prefix static assembly; dla HR drugim kosztem
   jest dynamiczna średnia.

ETAP 5E.2 zakończony. Dalsze prace zatrzymane; nie rozpoczęto optymalizacji
gauge ani ETAPU 5F.
