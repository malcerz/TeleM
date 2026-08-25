# TeleM — ETAP 10E: CPU_REFERENCE Chart HR/Cadence

## Zakres

Zoptymalizowano wyłącznie ścieżkę chartów w `src/indicators/chart_utils.py`.
Nie zmieniano moving window, danych telemetrycznych, z-order, compositora,
AMD/NVIDIA pipeline, presetów ani testów produkcyjnych.

## 1. Baseline 10D

| Stage | HR ms | Cadence ms |
|---|---:|---:|
| window/history prep | nie rozdzielono | nie rozdzielono |
| range/min/max | włączone w renderer | włączone w renderer |
| point generation | włączone w renderer | włączone w renderer |
| text measurement/layout | powtarzane | powtarzane |
| text drawing | powtarzane | powtarzane |
| polyline/fill | włączone w renderer | włączone w renderer |
| dynamic allocation/copy | włączone w renderer | włączone w renderer |
| total renderer | **12.866** | **6.162** |

Suma baseline: **19.028 ms/frame**.

## 2. Przyczyna różnicy HR/Cadence

Obie serie mają podobny rozmiar: odpowiednio 4299 i 4273 próbek w materiale
FIT. HR ma jednak `show_average=true`; jego ścieżka wykonuje dodatkową warstwę
średniej i większą liczbę operacji Pillow. Profil 10D wskazał około 75 operacji
primitive dla HR wobec 17 dla Cadence oraz około dwukrotnie więcej operacji
tekstowych/bbox w zagregowanym profilu.

## 3. Zmiana A — cache osi/layoutu

Dodano jeden bounded cache statycznej warstwy osi w `chart_utils.py`.
Cache obejmuje wyłącznie:

- osie, grid i ticki,
- stałe etykiety osi X/Y,
- wynik layoutu osi i bounds plotu.

Klucz zawiera rozmiar, supersampling, `show_axes`, grid, teksty etykiet,
rozmiar i ścieżkę fontu. HR i Cadence mają niezależne wpisy przez różne zakresy
etykiet. Dynamiczna seria, fill, średnia, cursor i finalny composite nadal są
rysowane w tej samej kolejności.

Limit: 64 wpisy. W benchmarku v10 użyto 2 wpisów osi; po pierwszym missie
pozostałe klatki korzystają z hitów. Cache nie jest globalnym cache'em bitmap
wartości i nie zależy od timestampu.

## 4. Benchmark lokalny po zmianie

Materiał: rzeczywisty `Jazda_na_rowerze_w_porze_lunchu.fit`, preset v10,
1280×720, 120 timestampów, bez wyłączania widgetów w rendererze chart.

| Variant | HR ms | Cadence ms | Sum |
|---|---:|---:|---:|
| baseline 10D | 12.866 | 6.162 | 19.028 |
| A — axis/layout cache | **0.923** | **0.886** | **1.810** |

Wyniki A są izolowanym renderem chartu bez pełnego AMD eksportera i bez
instrumentacji Pillow; nie należy ich porównywać jako bezpośredniego TRUE FPS.
Pokazują koszt lokalnego renderera na realnych danych po usunięciu powtarzanego
layoutu osi. Nie wykonywano wariantu B ani C, ponieważ profil po A nie wskazał
potrzeby dodawania cache bitmap wartości ani zmiany geometrii.

## 5. Pixel parity

Porównano cache miss i cache hit tej samej ścieżki renderera dla HR i Cadence,
przy timestampach 60 s, 180 s i 300 s:

```text
different pixels = 0
max channel delta = 0
```

Istniejące testy chart/window/prefix/dynamic-layer: **25 passed**.
W szczególności zachowano stałą oś activity, brak przyszłych próbek, gap
semantics oraz `None`/empty-history behavior.

## 6. Moving-window i semantyka danych

Nie wykonano downsample, resample, smoothing ani zmiany zakresu 60 s. Cache
przechowuje tylko warstwę niezależną od serii; bieżąca geometria i dynamiczne
elementy pozostają zależne od aktualnych danych.

## 7. Porównanie z 10B

| Metric | 10B baseline | 10E final |
|---|---:|---:|
| HR renderer | 12.866 | 0.923 isolated chart |
| Cadence renderer | 6.162 | 0.886 isolated chart |
| Chart sum | 19.028 | 1.810 isolated chart |
| above_compose | 33.236 | nie wykonano pełnego AMD run |
| above_total | 35.571 | nie wykonano pełnego AMD run |
| compose_overlay/below | 28.35 | poza zakresem |
| TRUE FPS | 8.893 | nie mierzono |
| RENDER FPS | 14.376 | nie mierzono |

## 8. Walidacja backendów

Nie zmieniono kodu AMD, NVIDIA, CPU compositora ani eksportera. Runtime AMD
Native full-v10 120-frame nie został uruchomiony w tym kroku; brak tej metryki
jest jawnie oznaczony powyżej. NVIDIA pozostaje statycznie zachowany i nie był
runtime-testowany.

## 9. Zmienione pliki

- `src/indicators/chart_utils.py` — bounded axis/layout cache.
- `Raporty/RAPORT_INDICATORS_ETAP_10E_CHART_CPU_OPTIMIZATION.md` — ten raport.

Nie zmieniono produkcyjnych plików poza chart helperem. Nie zmieniono presetów,
telemetrii, compositora, GPU pipeline ani testów produkcyjnych. Tymczasowe
skrypty profilujące usunięto.

## 10. Decyzja

**CHART CPU OPTIMIZATION: SUCCESS — NEXT PROFILE REMAINING CPU RENDERERS**

Cache osi usuwa potwierdzony koszt powtarzanego text metric/layout. Następny
etap powinien profilować pozostałe CPU renderery oraz wykonać pełny AMD Native
checkpoint, zanim zostanie oceniony wpływ na `above_compose` i FPS.
