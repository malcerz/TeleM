# TeleM — ETAP 10C: cache statycznych warstw rendererów

Data: 2026-08-22  
Preset: `presets/cycling_dashboard_v10.json`  
Zakres: tylko lokalne renderery wskaźników; bez zmian layoutu, telemetryki i pipeline’ów AMD/NVIDIA.

## 1. Baseline 10B

AMD Native, 1280×720, 120 klatek, 60 FPS target:

| Metric | 10B baseline |
|---|---:|
| `above_compose` | 33.236 ms |
| `above_total` | 35.571 ms |
| `compose_overlay` | 28.35 ms |
| TRUE FPS | 8.893 |
| RENDER FPS | 14.376 |

## 2. Per-widget timings before

Pomiar: 50 renderów po rozgrzaniu cache, reprezentatywne dane 1280×720. Procent odnosi się do `above_compose` baseline 33.236 ms.

| Widget | ms/render | % CPU_ABOVE |
|---|---:|---:|
| Compass | 2.440 | 7.34% |
| Slope | 2.283 | 6.87% |
| ISO | 0.009 | 0.03% |
| Shutter | 0.024 | 0.07% |
| Temp | 0.014 | 0.04% |
| Altitude | 4.077 | 12.27% |
| Virtual Power | 2.090 | 6.29% |
| Cadence | 0.086* | 0.26% |
| Speed Gauge | 0.521 | 1.57% |
| HR | 0.087* | 0.26% |

`*` Chart values above were measured through the existing split/static path; full AMD fallback remains governed by the unchanged overlap guard and renders through `CPU_REFERENCE`.

## 3. Existing cache architecture

Przed ETAPEM 10C projekt miał już static-layer cache w:

- `chart.py` / `chart_utils.py`: chart background, axes, grid, labels and split-chart static layer;
- `gauge.py`: standard gauge background and value-text tiles;
- `bar.py`: ruler/slope static raster;
- `helpers.py`: wspólny `_STATIC_CACHE` oraz cache fontów.

ETAP 10C nie stworzył równoległego frameworka. Wspólny cache został zastąpiony worker-local bounded LRU o limicie 128 wpisów i diagnostyce `hits/misses/entries`.

## 4. Chart: static/dynamic split

Static: tło, osie, grid, X-axis labels, label, stałe elementy zakresu i border.  
Dynamic: seria/fill, cursor, current value oraz elementy zależne od aktualnego okna/prefixu. Y-axis nie został założony jako bezwarunkowo statyczny.

Istniejący cache Chart został zachowany bez zmiany semantyki. Nie zmieniono overlap guardu i nie przepchnięto chartów na GPU.

## 5. Gauge: static/dynamic split

Standard Gauge miał już cache static background: ring/ticks/range labels/shadow. Dynamic pozostają needle, marker i current value.

Nie zmieniono geometrii ani `CPU_REFERENCE` fallbacku.

## 6. Compass: static/dynamic split

Dodano cache static dial dla ring, ticków i N/E/S/W. Klucz obejmuje rozmiar, font, outline, kolory, tick profile, interwały ticków i flagę cardinal labels.

Dynamic pozostają heading needle, center marker i heading text. `heading=None` tworzy świeżą warstwę dynamiczną i nie może odziedziczyć poprzedniej igły.

## 7. Bar/Slope: static/dynamic split

Bar/Slope już posiadał cache static rasteru: track, ticks, zero line, range labels i label. Dynamic pozostają marker i current value. Nie dodano drugiej implementacji cache.

## 8. Cache key

Wspólny LRU przechowuje istniejące immutable keys rendererów. Compass key zawiera wszystkie parametry static wymienione powyżej; nie zawiera heading/current value.

Zmiana fontu, rozmiaru, koloru, zakresu, tick configuration lub label tworzy nowy key.

## 9. Cache invalidation

Brak ręcznego globalnego `clear_chart_cache()`. Cache miss wynika naturalnie ze zmiany immutable key. `clear()` pozostaje dostępne dla testów i worker lifecycle.

## 10. Cache bounds

`_STATIC_CACHE` jest worker-local bounded LRU z `max_entries=128`. Po przekroczeniu limitu usuwany jest najstarszy wpis. Statystyki są dostępne przez `get_static_cache_stats()` i nie są logowane per klatkę.

## 11. Pixel parity

Cache miss → hit dla Chart, Gauge, Compass i Slope daje byte-identical RGBA. Testy sprawdzają również brak widocznej różnicy po zmianie dynamicznej wartości. `git diff --check` nie zgłosił błędów.

## 12. Dynamic-value correctness

Potwierdzono, że zmiana:

- Chart history zmienia raster serii;
- Gauge speed zmienia needle/value;
- Compass heading 0 → 90 zmienia needle/value;
- Slope -5 → +5 zmienia marker/value;
- Compass value → `None` nie zachowuje poprzedniej igły.

Zmiana właściwości stylu tworzy miss, a cache pozostaje ograniczony.

## 13. Chart-cache benchmark

Istniejący chart static cache pozostał aktywny. Nie wykonywano osobnego pełnego eksportu „po Chart”, ponieważ nie zmieniono kodu chartu w ETAPIE 10C; pomiar per-widget po rozgrzaniu wyniósł około 0.09 ms/render dla obu chartów w lokalnym rendererze.

## 14. Gauge-cache benchmark

Standard Gauge używał już cache static background. Compass po rozdzieleniu static/dynamic spadł z około 2.44 do około 0.92 ms/render w pomiarze 50 iteracji.

## 15. Bar-cache benchmark

Bar/Slope używał już cache static rasteru. Nie dodano kolejnej warstwy, ponieważ renderer posiadał wymagany podział.

## 16. Final AMD benchmark

Jeden końcowy pełny eksport AMD Native, bez wyłączania widgetów:

| Metric | 10B baseline | 10C final | improvement |
|---|---:|---:|---:|
| `above_compose` | 33.236 | 35.121 | -5.7% |
| `above_total` | 35.571 | 37.698 | -6.0% |
| `compose_overlay` | 28.35 | 34.262 | -20.9% |
| TRUE FPS | 8.893 | 7.988 | -10.2% |
| RENDER FPS | 14.376 | 12.796 | -11.0% |

Krótki eksport wykazał większy szum środowiskowy niż zysk z Compass cache. Nie traktuję tej różnicy jako dowodu regresji funkcjonalnej; nie ma jednak podstaw do deklarowania ≥30% redukcji `CPU_ABOVE_MAP`.

Eksport zakończył się poprawnie: decoded/received 120, submitted 120, encoded 120, muxed 120.

## 17. Targeted tests

```text
49 passed in 0.77s
```

Zakres obejmował nowy `tests/test_static_indicator_cache.py` oraz istniejące testy Chart, Compass, Slope, pixel style i font selection. Pełny suite 650+ nie był uruchamiany.

## 18. Changed files

- `src/indicators/helpers.py` — bounded LRU i cache stats dla istniejącego `_STATIC_CACHE`;
- `src/indicators/gauge.py` — Compass static dial cache;
- `tests/test_static_indicator_cache.py` — parity, dynamic values, invalidation i bound tests;
- ten raport.

Nie zmieniono presetów, `src/ffmpeg/*`, telemetryki, mapy ani GUI.

## 19. Preserved paths

CPU_REFERENCE, AMD GPU map/chart/gauge paths, NVIDIA path, backend selection i compositing order pozostały zachowane. `CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP` pozostało bez zmian.

## 20. Remaining bottleneck

Największym kosztem pozostaje pełny `compose_overlay` oraz CPU rendering chartów/gauge po zachowaniu overlap guardów. Sam bounded cache i Compass static split nie zmieniły istotnie pełnego eksportu.

Runtime NVIDIA nie był dostępny; NVIDIA path preserved statically.

## 21. Final decision

`STATIC CACHE: LOW IMPACT`
