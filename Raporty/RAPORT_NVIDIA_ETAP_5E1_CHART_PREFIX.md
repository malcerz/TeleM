# RAPORT NVIDIA ETAP 5E.1 — Chart Prefix / Activity-to-Current Semantics

Data: 2026-08-20  
Zakres: wyłącznie `fit_cadence_text` i `fit_heart_rate_text`.

Nie zmieniano: gauge, alpha compositing, preview, FIT dynamic discovery,
battery/solar, MAX5, GRID16, Direct-Region, atlasu, telemetry precompute,
SmartSync, workers/MAX_IN_FLIGHT ani FFmpeg/NVENC/NVDEC.

## 1. Implementacja

Wcześniejszy renderer używał statycznego rastra całej aktywności i przesuwał
tylko marker. W ETAPIE 5E.1 dodano stateless prefix renderer w
`src/indicators/chart_utils.py`.

Mechanizm składa się z trzech warstw:

1. Immutable cache osi, zakresu wartości, punktów bazowych i segment ranges.
2. `bisect_right(timestamps, current_time)` wybierający tylko próbki
   `timestamp <= current_time`.
3. Per-frame raster prefixu: X widocznych punktów jest mapowany na domenę
   `activity_start → current_time`; serie są rysowane wyłącznie z cached
   segment ranges.

Nie ma mutacji `ChartHistory`, sliding window ani worker-specific state.
Przy 100% funkcja zwraca pełny raster z dotychczasowego generatora, zachowując
pełną historię i jego rasterization order.

W `src/indicators/chart.py` prefix dynamiczny jest używany dla obu wykresów.
Marker nie korzysta już z próbki przyszłej: pomiędzy próbkami pozostaje na
ostatniej próbce widocznej w prefixie; w luce nie jest tworzona interpolowana
linia.

## 2. Semantyka danych

- `cadence=0.0` pozostaje zwykłym punktem danych;
- `None` pozostaje missing;
- `None` dzieli segment;
- długa luka dzieli segment;
- segmenty przed luką pozostają widoczne po przejściu przez lukę;
- pierwszy sample pozostaje pierwszym samplem przy każdym current time;
- próbki z timestampem większym niż current nie są rysowane.

## 3. Referencyjny renderer i pixel parity

Test referencyjny tworzy nowy `ChartHistory` zawierający wyłącznie próbki
`<= current_time` i przekazuje go do istniejącego, nieoptymalizowanego
rendererera. Wynik prefix rendererera porównywany jest do tego obrazu w raw
RGBA. Nie porównywano poprawnego prefixu z dawnym, błędnym full-history
rastram.

Checkpointy:

- 0%, 10%, 25%, 50%, 75%, 90%, 100%;
- przed długą luką;
- wewnątrz luki;
- na pierwszym punkcie po luce.

Wszystkie wymagane porównania referencyjne przechodzą:

```text
max_diff = 0
different_pixels = 0
```

Testy znajdują się w
`tests/test_etap5e1_chart_prefix.py`. Obejmują również osobne timestampy
cadence i HR.

## 4. Benchmark chart-only A/B — 1000 wywołań

Materiałowy FIT referencyjny, rzeczywiste historie, rozgrzane cache.

| Chart | Wariant | avg ms | median ms | p95 ms |
| --- | --- | ---: | ---: | ---: |
| cadence | stary cached full-history | 0.148 | 0.146 | 0.157 |
| cadence | naiwny poprawny prefix | 2.037 | 1.628 | 3.625 |
| cadence | zoptymalizowany poprawny prefix | 1.035 | 0.880 | 1.522 |
| HR | stary cached full-history | 0.145 | 0.142 | 0.155 |
| HR | naiwny poprawny prefix | 1.966 | 1.516 | 3.276 |
| HR | zoptymalizowany poprawny prefix | 1.075 | 0.944 | 1.478 |

Suma cadence+HR:

| Wariant | avg ms | median ms | p95 ms |
| --- | ---: | ---: | ---: |
| stary full-history | 0.293 | 0.288 | 0.312 |
| naiwny correct-prefix | 4.003 | 3.144 | 6.901 |
| nowy optimized-prefix | 2.110 | 1.824 | 3.001 |

Nowa implementacja redukuje koszt poprawnego prefixu o około 47% względem
naiwnego wariantu.

## 5. Worker-like pomiar

Pomiar 300 wywołań `compose_overlay` z obiema aktywnymi historiami i
różnymi timestampami:

```text
avg    5.855 ms
median 5.834 ms
p95    7.015 ms
```

Jest to pomiar lokalnego worker-like compose, nie czas całego eksportu.

## 6. Produkcyjny benchmark — 3 eksporty

Uruchomiono trzy eksporty `GX030120.MP4` +
`Popoludniowa_jazda_na_rowerze_solar_battery.fit`, preview ON, workers=4,
MAX_IN_FLIGHT=8, MAX5, GRID16, MULTI_REGION_ATLAS i DIRECT_REGION.

Każdy eksport potwierdził:

```text
HUD producer: DIRECT_REGION
HUD mode: MULTI_REGION_ATLAS
HUD regions: 5
HUD atlas: 1900x762
```

| Run | FRAME_PIPELINE FPS | REAL_EXPORT FPS | preview updates/s |
| ---: | ---: | ---: | ---: |
| 1 | 225.8 | 210.5 | 4.21 |
| 2 | 225.4 | 212.8 | 4.26 |
| 3 | 203.4 | 193.4 | 3.87 |
| **median** | **225.4** | **210.5** | **4.21** |

`ffmpeg_write`:

```text
run 1: avg 3.77 ms, p95 13.35 ms
run 2: avg 3.30 ms, p95 10.32 ms
run 3: avg 2.92 ms, p95  7.62 ms
```

Pliki pomiarowe:

- `scratch/benchmark_etap5e1_prefix.py`;
- `scratch/etap5e1_prefix_benchmark.json`;
- `scratch/benchmark_etap5e1_production.py`;
- `scratch/etap5e1_production.log`;
- `scratch/etap5e1_production_results.json`.

Lokalna para materiałowa ma historycznie niespójne absolutne timestampy
GPMF/FIT (`GPMF 04:46 UTC`, FIT `13:00–14:01`), więc eksport produkcyjny
potwierdza ścieżkę NVIDIA i jej wydajność, ale chart-only A/B jest właściwym
pomiarom semantyki prefixu na rzeczywistych historiach FIT. Nie zmieniano
SmartSync w tym etapie.

## 7. Testy

```text
pytest -q \
  tests/test_etap5e1_chart_prefix.py \
  tests/test_chart_rendering.py \
  tests/test_chart_static_assembly_etap5d.py \
  tests/test_nvidia_regression_chart_preview.py \
  tests/test_etap8e_full_activity_charts.py \
  tests/test_etap8m4_chart_time_scope.py \\ 
  tests/test_etap5b2_chart_precompute_regression.py

32 passed in 2.80s
```

## 8. Odpowiedzi końcowe

1. `activity start → current time` zrealizowano przez stateless
   `bisect_right` i dynamiczne mapowanie widocznego prefixu na bieżącą domenę;
   pełna geometria i granice segmentów są cache’owane.
2. Nie. Próbka z `timestamp > current_time` nie trafia do prefix rastera.
3. Tak. `cadence=0.0` nie jest usuwane, interpolowane ani traktowane jako
   missing.
4. Tak. `_split_chart_segments` nadal rozcina przy `None` i długiej luce.
5. Cadence+HR: stary błędny full-history **0.293 ms**, nowy poprawny prefix
   **2.110 ms avg**, **1.824 ms median**, **3.001 ms p95**. Nowy prefix jest
   około 47% szybszy od naiwnego poprawnego prefixu (**4.003 ms avg**).
6. Nowy median `FRAME_PIPELINE`: **225.4 FPS**.
7. Największym hotspotem chartów pozostaje dynamiczny raster/compositing
   prefixu i etykieta bieżącej wartości. W worker-like compose całość kosztuje
   medianę **5.834 ms**; gauge nie był zmieniany ani optymalizowany.

ETAP 5E.1 zakończony. Dalsza praca zatrzymana.
