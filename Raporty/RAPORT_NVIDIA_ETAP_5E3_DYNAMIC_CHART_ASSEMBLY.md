# RAPORT NVIDIA ETAP 5E.3 — Dynamic Prefix Assembly + HR Average Fast Path

Data: 2026-08-20  
Zakres: wyłącznie `fit_cadence_text`, `fit_heart_rate_text` oraz bezpieczeństwo ich cache.

Nie zmieniano gauge, preview, Direct-Region, atlasu, MAX5, GRID16,
telemetry precompute, FIT discovery, SmartSync, workers/MAX_IN_FLIGHT,
NVDEC/NVENC ani semantyki `None`/zero.

## A. 5E.2 detailed hotspot profile

Profil obejmował 1000 wywołań każdego wykresu z aktywnym profilerem.
Pomiar obejmuje także narzut instrumentacji Pillow, dlatego służy do
porównania faz, a nie jako bezpośredni czas eksportu.

| Faza | Cadence ms | HR ms | Razem ms |
|---|---:|---:|---:|
| bisect/current index | 0,001 | 0,001 | 0,002 |
| segment selection | 0,001 | 0,001 | 0,002 |
| X mapping / point list | 0,048 | 0,050 | 0,098 |
| polygon/fill | 0,120 | 0,063 | 0,183 |
| polyline | 0,026 | 0,023 | 0,049 |
| image copy | 0,064 | 0,061 | 0,125 |
| prefix static assembly | 0,434 | 0,434 | 0,868 |
| cursor + current dot | 0,056 | 0,054 | 0,110 |
| dynamic current label | 0,121 | 0,134 | 0,255 |
| HR average line | 0,000 | 0,287 | 0,287 |

Bisect, segment selection i X/Y mapping nie są obecnie głównym hotspotem.

## B. Unique prefix/current states

Dla 5400 klatek policzono widoczny indeks próbki względem początku
aktywności, osobno dla każdej serii FIT:

| Seria | Unikalne indeksy | Cache hits — hipotetyczny cache per indeks | Hit rate | Średnio klatek / stan |
|---|---:|---:|---:|---:|
| cadence | 162 | 5238 | 97,00% | 33,33 |
| HR | 168 | 5232 | 96,89% | 32,14 |

Cadence zawierało 2428 widocznych klatek z rzeczywistym `0.0` oraz 210
klatek z wartością `None`; zera nie zostały potraktowane jako missing.

## C. Cache feasibility

Cache całego prefix rastera wyłącznie po:

```text
(history identity, style, last_visible_sample_index)
```

nie jest bezpieczny przy obecnym Modelu A. Dwie klatki mogą mieć ten sam
`last_visible_sample_index`, ale różny dokładny `current_time`. Wtedy zmienia
się skala osi X wszystkich widocznych punktów.

Diagnostyka kwantyzacji `current_time` do timestampu ostatniej próbki wykazała
przykładowo:

```text
cadence: max_diff=255, do 3870 różnych pikseli
HR:      max_diff=255, do 728 różnych pikseli
```

W związku z tym nie wdrożono cache rastera per visible index ani kwantyzacji
czasu.

Wykryto i naprawiono natomiast niezależny błąd bezpieczeństwa: wcześniejszy
klucz oparty o `id(history)` mógł kolidować po ponownym użyciu ID obiektu przez
Pythona. `ChartHistory` ma teraz monotoniczny worker-local token cache, więc
tymczasowa historia nie może odziedziczyć geometrii innej historii.

## D. HR average analysis

5E.2 już przechowuje w metadanych geometrii `cumulative_sum` i
`cumulative_count`; odczyt średniej jest O(1). Dla 5400 klatek HR wystąpiło
168 stanów widocznego prefixu, a cache średniej kluczowany bezpiecznie po
widocznym indeksie miałby 96,89% hit rate.

Sama linia średniej jest zależna od Y i nadal jest rysowana dynamicznie.
Próba dodatkowego raster cache linii nie dawała istotnego zysku względem
kosztu pamięci i kompozycji, dlatego nie została wdrożona.

## E. Current-label analysis

W 5400 klatkach wystąpiło:

| Seria | Unikalne sformatowane wartości | Hipotetyczny hit rate cache po stringu |
|---|---:|---:|
| cadence | 34 | 99,37% |
| HR | 14 | 99,74% |

To potwierdza, że bounded cache stringów byłby możliwy. Nie wdrożono jednak
cache glyph rastera w prefix path: transparentny tile wklejany przez `paste`
nie zachowuje dokładnie tych samych pikseli co bezpośrednie `ImageDraw.text`
na istniejącym headerze. Cache samego bboxa oszczędzałby tylko małą część
kosztu etykiety i nie spełnia kryterium stabilnej redukcji co najmniej 20%.

## F. Cursor analysis

Cursor wraz z kropką kosztuje w profilu około `0,056 ms` dla cadence i
`0,054 ms` dla HR. Jego X zmienia się przy każdym dokładnym `current_time`,
więc pozostaje dynamiczny. Nie zmieniono grubości, alpha ani antyaliasingu.

## G. Dynamic ROI analysis

Header i geometria osi/grid są cache’owane. 5E.2 używa także worker-local
reusable buffera `header + prefix`: prostokąt chartu jest czyszczony, nowy
prefix wklejany, a wynik zwracany jako niezależna kopia.

Dalsze zmniejszenie ROI nie rozwiązuje głównego kosztu, ponieważ w Modelu A
każda zmiana czasu skaluje cały widoczny prefix. Sam prefix ROI jest więc
dynamiczny na całej szerokości chartu. Nie wprowadzono złożonego rozdzielenia
na dodatkowe warstwy.

## H. Implemented optimizations

W tym etapie wdrożono wyłącznie minimalną poprawkę bezpieczeństwa cache:

- `src/indicators/chart_builder.py` — stabilny monotoniczny token każdego
  `ChartHistory`;
- `src/indicators/chart_utils.py` — użycie tokenu w kluczu geometrii zamiast
  samego `id(history)`;
- `tests/test_etap5e3_dynamic_prefix.py` — test powtarzających się stanów,
  exact current-time semantics, zero i luka.

Nie wdrożono niepoprawnego cache prefix rastera, kwantyzacji czasu ani nowego
cache glyph/average rastera. Istniejące zyski 5E.2 — precomputed X/Y,
segment ranges, cumulative sum/count i reusable buffer — pozostają aktywne.

## I. Cache hit rates

| Cache / strategia | Cadence | HR | Status |
|---|---:|---:|---|
| prefix raster per visible index | 97,00% hipotetycznie | 96,89% hipotetycznie | odrzucony — łamie Model A |
| HR average per visible index | — | 96,89% | istnieje bezpieczny stan O(1), bez nowego raster cache |
| current label per formatted string | 99,37% hipotetycznie | 99,74% hipotetycznie | nie wdrożono glyph paste z powodu parity |
| prefix geometry metadata | worker-local | worker-local | aktywny, token-safe |

## J. Pixel parity

Referencją pozostaje naiwny correct-prefix renderer 5E.1. Sprawdzono
checkpointy, punkty pomiędzy próbkami, stan przed/w trakcie/po luce oraz
powtarzające się visible index.

Wymagane testy zakończyły się:

```text
66 passed
max_diff = 0
different_pixels = 0
```

Dotyczy to poprawnego exact-prefix renderera. Diagnostyczna kwantyzacja czasu
nie spełnia parity i nie jest używana produkcyjnie.

## K. Chart-only benchmark

1000 wywołań na identycznym materiale i konfiguracji. Wynik 5E.3 jest
wynikiem aktualnego renderera po minimalnej poprawce cache identity; ponieważ
nie wdrożono dodatkowego prefix/average raster cache, jest praktycznie równy
5E.2.

| Wariant | Seria | avg ms | median ms | p95 ms |
|---|---|---:|---:|---:|
| correct-prefix 5E.1 | cadence | 1,035 | 0,880 | 1,522 |
| fast-prefix 5E.2 | cadence | 0,823 | 0,730 | 1,140 |
| 5E.3 current | cadence | **0,811** | **0,699** | **1,173** |
| correct-prefix 5E.1 | HR | 1,075 | 0,944 | 1,478 |
| fast-prefix 5E.2 | HR | 0,842 | 0,776 | 1,061 |
| 5E.3 current | HR | **0,833** | **0,762** | **1,062** |

Suma cadence + HR, liczona jako suma niezależnych pomiarów:

```text
5E.1: 2,110 ms avg
5E.2: 1,665 ms avg
5E.3: 1,644 ms avg
```

Różnica 5E.3 względem 5E.2 mieści się w szumie pomiarowym; nie ma podstaw
do komplikowania renderera dla kilku procent.

## L. Worker profiler including gauge

Worker-like profiler obejmował 300 wywołań `compose_overlay`, obie aktywne
historie wykresów oraz niezmieniony gauge `fit_enhanced_speed_text`.

| Komponent | avg ms | median ms | p95 ms |
|---|---:|---:|---:|
| cadence total | 1,497 | 1,548 | 1,690 |
| HR total | 1,731 | 1,709 | 1,845 |
| cadence + HR | 3,228 | 3,256 | 3,534 |
| gauge `fit_enhanced_speed_text` | 0,383 | 0,381 | 0,473 |
| worker-like compose total | 6,538 | 6,679 | 7,227 |

Gauge nie był modyfikowany.

## M. Production benchmark

Wykonano trzy pełne eksporty:

```text
GX030120.MP4
Popoludniowa_jazda_na_rowerze_solar_battery.fit
MAX5, GRID16, MULTI_REGION_ATLAS, DIRECT_REGION
preview ON, workers=4, MAX_IN_FLIGHT=8
```

Każdy run potwierdził `DIRECT_REGION`, `MULTI_REGION_ATLAS`, 5 regionów,
atlas `1900x762`, `FRAME_PIPELINE` oraz preview.

| Run | FRAME_PIPELINE FPS | REAL_EXPORT FPS | preview FPS |
|---:|---:|---:|---:|
| 1 | 228,1 | 213,4 | 4,268 |
| 2 | 228,4 | 215,9 | 4,317 |
| 3 | 226,6 | 213,9 | 4,277 |
| **mediana** | **228,1** | **213,9** | **4,277** |

`ffmpeg_write`:

```text
run 1: avg 4,19 ms, p95 13,58 ms
run 2: avg 4,13 ms, p95 14,53 ms
run 3: avg 4,18 ms, p95 14,93 ms
mediana: avg 4,18 ms, p95 14,53 ms
```

Chart total, gauge i worker-like total w tabeli L są pomiarem profilera
komponentowego, a nie osobnym timerem raportowanym przez eksport FFmpeg.

## N. New bottleneck

Największym celem pozostaje dynamiczne składanie prefixu — około `0,434 ms`
na chart w profilu fazowym — oraz rasteryzacja fill/polyline. Dla HR dochodzi
dynamiczna linia średniej około `0,287 ms` w profilu z narzutem Pillow.

Gauge kosztuje około `0,383 ms` i jest wyraźnie mniejszy od łącznego kosztu
chartów około `3,228 ms` w worker-like compose. Po 5E.3 nie ma podstaw, aby
przechodzić do optymalizacji gauge.

## Odpowiedzi końcowe

1. W 5400 klatkach występuje 162 unikalnych stanów cadence i 168 unikalnych
   stanów HR.
2. Nie. Cache prefixu pomiędzy próbkami po samym indeksie łamie Model A,
   ponieważ dokładny current time zmienia geometrię X.
3. Zachowano bezpieczne `cumulative_sum/count` dla HR oraz reusable/static
   cache z 5E.2. Nie wdrożono nowego raster cache średniej ani glyph cache
   etykiet; istniejące wartości wskazują jedynie hipotetyczne hit rate.
4. Cadence kosztuje `0,811 ms avg`, HR `0,833 ms avg`, razem około
   `1,644 ms avg`.
5. Tak. Correct-prefix parity pozostaje `max_diff=0` i
   `different_pixels=0`; kwantyzacja czasu została odrzucona.
6. Mediana `FRAME_PIPELINE` wynosi `228,1 FPS`.
7. Gauge kosztuje `0,383 ms avg`, `0,381 ms median`, `0,473 ms p95`.
8. Nadal chart jest większym celem. Gauge pozostaje bez zmian; po tym etapie
   optymalizacje są zatrzymane.

ETAP 5E.3 zakończony. Dalsza optymalizacja zatrzymana.
