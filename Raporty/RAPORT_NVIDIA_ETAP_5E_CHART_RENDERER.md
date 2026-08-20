# NVIDIA ETAP 5E — Chart Renderer Optimization

Data audytu: 2026-08-20.  Zakres: wyłącznie `fit_cadence_text` i
`fit_heart_rate_text`; nie zmieniono rendererów produkcyjnych, Direct-Region,
atlasu, preview, parametrów NVENC/NVDEC, workerów ani danych telemetrycznych.

## A. Current call graph

`streaming` → worker `render_overlay_frame` → `TelemetryFrameCache.lookup` →
`compose_overlay` → `render_value_indicator` → `_render_chart_indicator` →
`get_history_chart_background`.

`TelemetryFrameCache` przekazuje ten sam, niemutowalny `ChartHistory` każdej
klatce.  `ChartHistory` zawiera wartości, tuple timestampów oraz granice osi
czasu.  Renderer buduje tło z `get_history_chart_background`, a następnie dla
każdej klatki wylicza pozycję kursora (`bisect_right`) i aktualną wartość.

## B. Detailed profiler

Świeży profil: 1000 wywołań każdego wykresu, layout produkcyjny, rzeczywiste
historie referencyjnego FIT; cache rozgrzany. Artefakt:
`scratch/etap5e_chart_profile_before.json`.

| Phase | Cadence ms | HR ms | Total ms |
| --- | ---: | ---: | ---: |
| pełne wywołanie, avg | 0.246 | 0.247 | 0.493 |
| pełne wywołanie, median | 0.240 | 0.239 | 0.479 |
| pełne wywołanie, p95 | 0.288 | 0.273 | 0.561 |
| dynamic labels | 0.107 | 0.113 | 0.220 |
| cursor | 0.056 | 0.054 | 0.110 |
| final background/chart composite | 0.080 | 0.078 | 0.159 |
| history/cache + current-time lookup | 0.013 | 0.014 | 0.027 |
| static background axes/grid/polyline | 0.003 amortized | 0.005 amortized | 0.008 |
| copy lokalnego rastra | 0.017 | 0.017 | 0.033 |

Cache lookup, timestampowe `bisect_right`, slicing, wykrywanie segmentów,
obliczenie X/Y, listy punktów, polygon i `ImageDraw.line` nie występują w
gorącej ścieżce. Są wykonywane przy pojedynczym cache miss.

## C. Static/dynamic analysis

Static per export: wartości, timestampy, granice aktywności, min/max, X/Y,
segmenty z lukami, tło, osie, grid, etykiety i finalny statyczny raster.

Dynamic per frame: wyrównanie `target_dt`, indeks kursora, pionowy cursor/dot
oraz tekst bieżącej wartości. Renderer jest stateless; nie zakłada kolejności
klatek ani przypisania kolejnych klatek temu samemu workerowi.

## D. Gap/segment analysis

`_split_chart_segments` rozdziela serię dla `None` i dla luki większej niż
`max(5 s, 3 × median odstępu)`. Realne `cadence=0` nie rozdziela segmentu.
Nie zmieniono tej naprawy regresji.

## E. X/Y precompute

X/Y oraz segmenty są de facto już precomputed przez `_CHART_BG_CACHE`:
cache przechowuje raster tła i gotową listę punktów dla tożsamości historii,
geometrii i stylu. Dodatkowy cache tych samych danych byłby konkurencyjny,
zwiększyłby złożoność i nie usunął dominującego kosztu tekstu/kursora.

## F. Implemented optimization

Nie wdrożono nowej zmiany kodu produkcyjnego. Obecny cache statycznego rastra
jest już właściwą optymalizacją ETAPU 5E; profil nie uzasadnia dublowania
cache ani stateful/incremental renderer. Dodano wyłącznie reprodukowalny
profil audytowy `scratch/profile_etap5e_charts.py`.

## G. Cadence zero semantics

Bez zmian: `0.0` jest daną, pozostaje na wykresie i nie jest zamieniane na
`None`, poprzednią wartość ani interpolację.

## H. Full-history semantics

Wykryto istotną niespójność między bieżącym kodem a kontraktem zadania.
Aktualny `ChartHistory` obejmuje całą aktywność, a statyczny raster renderuje
od razu wszystkie jego próbki. `target_dt` przesuwa tylko kursor. Zatem
obecny raster pokazuje również próbki późniejsze niż bieżący czas.

To nie jest ani sliding window, ani kontrakt „start aktywności → aktualny
czas” z zakazem przyszłych próbek. Naprawa wymagałaby świadomej zmiany obrazu
(prefix/reveal historii), więc nie może jednocześnie spełnić wymaganego
`max_diff=0` względem obecnego rastra i zakazu zmiany wyglądu. Nie ukryto tej
różnicy pod pozorem optymalizacji.

## I. Gap semantics

Zachowane: `None` i długa luka dzielą linię oraz fill; nie powstaje sztuczne
połączenie przez gap ani spadek do baseline. `None != 0`.

## J. Pixel parity

Nie ma zmiany produkcyjnego renderer, więc nie ma wariantu AFTER do porównania.
Istniejąca kontrola surowego RGBA dla pozycji kursora przechodzi:
`tests/test_chart_static_assembly_etap5d.py`.

Nie sfałszowano testu „prefix bez przyszłych próbek”: przy aktualnym rendererze
musiałby on poprawnie wykazać opisany w sekcji H problem. Przed takim testem
i implementacją trzeba wybrać nadrzędny kontrakt: pixel parity obecnego
pełnego rastra albo semantyczny prefix historii.

## K. Renderer benchmark

| Chart | BEFORE avg | AFTER avg | Reduction |
| --- | ---: | ---: | ---: |
| cadence | 0.246 ms | 0.246 ms | 0% — brak bezpiecznej zmiany |
| HR | 0.247 ms | 0.247 ms | 0% — brak bezpiecznej zmiany |
| TOTAL | 0.493 ms | 0.493 ms | 0% |

Największy koszt pojedynczego chart renderer to dynamiczny tekst, nie
geometria historii. Optymalizacja geometrii nie osiągnęłaby progu 40%.

## L. Worker profiler

Świeży profil chart-only wskazuje 0.493 ms łącznie dla obu widgetów. Ostatni
porównywalny pełny worker profile (`scratch/etap5d_optimized_profile.json`)
pokazuje, że w pełnej kompozycji dominują `alpha_composite`, tekst i lokalne
compositing; gauge nie został mierzony ani zmieniony w tym etapie.

## M. Production benchmark 3×

Nie uruchomiono nowych trzech eksportów: brak zmiany produkcyjnej oznaczałby
wyłącznie powtórzenie istniejącego benchmarku, a lokalna bezpośrednia para
GPMF/FIT ma obecnie niespójne czasy (`GX030120` 04:46 UTC, FIT 13:00–14:01).
Bez uruchamiania właściwego, niezmienianego SmartSync eksport nie renderuje
tych chartów i nie byłby poprawnym benchmarkiem ETAPU 5E.

Ostatni ważny, już zapisany benchmark MAX5 z preview ON:
median REAL_EXPORT **207.7 FPS**, 108 aktualizacji preview / eksport,
**4.15 updates/s**. `FRAME_PIPELINE` z logu: około **219.4 FPS** median
(24.520 s dla 5400 klatek). To jest baseline, nie nowy wynik ETAPU 5E.

## N. New bottleneck

Po istniejącym cache geometrii wykresu wąskim gardłem chartów jest dynamiczna
etykieta tekstowa i cursor/composite. Szerszy worker hotspot pozostaje poza
zakresem ETAPU 5E (kompozycja alpha/tekst oraz inne wskaźniki); nie zmieniano
gauge.

## Testy

Wykonano:

```text
pytest -q tests/test_chart_static_assembly_etap5d.py \
          tests/test_nvidia_regression_chart_preview.py \
          tests/test_etap8e_full_activity_charts.py \
          tests/test_etap8m4_chart_time_scope.py
20 passed in 0.26s
```

## Wniosek

> Co dokładnie było największym kosztem chart renderer?

Dynamiczny tekst (~0.22 ms dla obu), następnie cursor (~0.11 ms) i złożenie
lokalnego rastra (~0.16 ms); nie segmenty ani X/Y.

> Ile kosztowały cadence + HR przed i po?

0.493 ms średnio łącznie; po = przed, ponieważ nie wdrożono nieuzasadnionej
zmiany.

> Czy wykres nadal zaczyna się od początku aktywności?

Tak, lecz obecnie pokazuje całą aktywność, łącznie z przyszłymi próbkami.

> Czy cadence=0 pozostaje prawidłowym zerem?

Tak.

> Czy długa luka FIT nadal dzieli polilinię?

Tak.

> Czy rastery i cały atlas są bit-identyczne?

Tak względem bieżącej ścieżki, bo nie zmieniono renderera; nie wykonano
fałszywego porównania z semantycznie innym prefixem.

> Jaki jest nowy FRAME_PIPELINE FPS?

Nie ma nowego wyniku; obowiązuje ważny baseline około 219.4 FPS z benchmarku
MAX5/preview ON.

> Czy gauge jest teraz największym renderer hotspotem?

Nie ustalono tego w tym etapie; gauge pozostał poza zakresem.

ETAP 5E zatrzymany po audycie, zgodnie z zasadą niełączenia niezgodnej zmiany
semantyki z optymalizacją.
