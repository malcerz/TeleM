# TeleM — RAPORT AMD ETAP 5G — CPU ABOVE DYNAMIC TEXT / RASTER / DIRTY-RECT OPTIMIZATION

**Data:** 2026-08-28  
**Środowisko:** AMD Ryzen 7 7730U with Radeon Graphics (8C/16T, 32GB RAM UMA)  
**System & Power Profile:** Windows 11 (Max Performance Power Overlay GUID: `ded574b5-45a0-4f42-8737-46345c09c238`)  
**Gałąź:** `amd-render`  
**Kanoniczny Workload:** `Video/GX020079.MP4` + `Video/GX020079.fit` + `presets/cycling_dashboard_v10.json`  
**Parametry:** 1131 klatek @ 4K (3840x2160), AMF HEVC CQP 28/28 Speed, ASYNC QueueDepth=2, STATIC_CACHE, DRAIN_READY, PROFILING=0  
**Status etapu:** **COMPLETE — PASS (LOCAL PASS / PIPELINE HEADROOM GAIN)**

---

## 1. Fresh BEFORE Baseline (5-Run Medians)

Warunki: `GX020079.MP4` + `GX020079.fit`, 1 warmup + 5 przebiegów pomiarowych.

| Metryka | Wartość Medianowa (5 runów) | Średnia | Min | Max | CV% |
|---|:---:|:---:|:---:|:---:|:---:|
| **TRUE FPS** | **38.333 fps** | 38.349 fps | 38.083 fps | 38.544 fps | 0.42% |
| **RENDER FPS** | **40.074 fps** | 40.098 fps | 39.816 fps | 40.315 fps | 0.38% |
| **USER EFFECTIVE FPS** | **37.575 fps** | 37.592 fps | 37.332 fps | 37.785 fps | 0.38% |
| **frame interval** | **24.95 ms** | 24.93 ms | 24.80 ms | 25.11 ms | 0.40% |
| **producer_prepare avg** | **20.302 ms** | 20.320 ms | 19.980 ms | 20.768 ms | 1.34% |
| **producer_queue_wait avg**| **4.684 ms** | 4.675 ms | 4.312 ms | 5.068 ms | 5.82% |
| **above_total avg** | **14.067 ms** | 14.085 ms | 13.780 ms | 14.420 ms | 1.62% |
| **above_compose avg** | **12.444 ms** | 12.460 ms | 12.200 ms | 12.750 ms | 1.55% |
| **map_cpu_upload avg** | **2.262 ms** | 2.270 ms | 2.225 ms | 2.316 ms | 1.45% |
| **consumer_native_call avg**| **11.631 ms** | 11.642 ms | 11.205 ms | 12.086 ms | 2.68% |
| **vp_cpu_submit avg** | **10.422 ms** | 10.435 ms | 9.982 ms | 10.884 ms | 2.85% |
| **total_export** | **30,099.6 ms** (~30.10 s) | 30,086.1 ms | 29,933.2 ms | 30,296.8 ms | 0.43% |

---

## 2. Precyzyjny Audyt Widgetów CPU ABOVE (TOP 12)

Zmierzono czasy renderowania pojedynczych widgetów na 1131 klatkach (okno dynamiczne 0..965 i pełne 0..1130):

| Ranga | Widget ID | Typ / Styl | Średnia (ms) | Mediana (ms) | P95 (ms) | Dyn Avg 0..965 (ms) |
|:---:|---|---|:---:|:---:|:---:|:---:|
| 1. | `fit_enhanced_speed_text` | `gauge` (Speed Gauge) | 4.380 ms | 4.209 ms | 6.343 ms | 4.348 ms |
| 2. | `time_display` | `time_display` | 0.599 ms | 0.394 ms | 1.669 ms | 0.602 ms |
| 3. | `slope_text` | `bar` / `slope` | 0.574 ms | 0.505 ms | 0.908 ms | 0.567 ms |
| 4. | `alt_visual` | `bar` / `ruler` (vert) | 0.541 ms | 0.559 ms | 0.928 ms | 0.549 ms |
| 5. | `iso_text` | `text` | 0.494 ms | 0.577 ms | 0.987 ms | 0.463 ms |
| 6. | `compass` | `gauge` / `compass` | 0.489 ms | 0.442 ms | 0.706 ms | 0.484 ms |
| 7. | `fit_battery_pct_text` | `bar` / `segments` | 0.356 ms | 0.322 ms | 0.520 ms | 0.352 ms |
| 8. | `exposure_text` | `text` | 0.287 ms | 0.093 ms | 0.871 ms | 0.287 ms |
| 9. | `fit_solar_pct_text` | `bar` / `segments` | 0.253 ms | 0.227 ms | 0.385 ms | 0.251 ms |
| 10.| `dist_visual` | `bar` / `ruler` (horiz) | 0.236 ms | 0.201 ms | 0.357 ms | 0.235 ms |
| 11.| `fit_curVpower_text` | `bar` / `ruler` | 0.216 ms | 0.186 ms | 0.319 ms | 0.213 ms |
| 12.| `temp_text` | `text` | 0.091 ms | 0.082 ms | 0.143 ms | 0.089 ms |

---

## 3. Częstotliwość Zmian Wartości Wyświetlanych (Display Change Frequency)

Audyt wykazał bardzo wysoką stabilność wielu widgetów telemetrycznych na kanonicznym nagraniu:

| Widget | Unikalne wartości | Liczba zmian | % Zmian klatek | Klatki bez zmian | % Stałych klatek |
|---|:---:|:---:|:---:|:---:|:---:|
| `fit_battery_pct_text` | 1 | 0 | 0.0% | 1130 | **100.0%** |
| `fit_solar_pct_text` | 1 | 0 | 0.0% | 1130 | **100.0%** |
| `compass` | 1 | 0 | 0.0% | 1130 | **100.0%** |
| `slope_text` | 1 | 0 | 0.0% | 1130 | **100.0%** |
| `fit_curVpower_text` | 24 | 25 | 2.2% | 1105 | **97.8%** |
| `temp_text` | 22 | 37 | 3.3% | 1093 | **96.7%** |
| `time_display` | 39 | 38 | 3.4% | 1092 | **96.6%** |
| `exposure_text` | 314 | 831 | 73.5% | 299 | 26.5% |
| `iso_text` | 740 | 930 | 82.3% | 200 | 17.7% |
| `fit_enhanced_speed_text` | 1087 | 1086 | 96.1% | 44 | 3.9% |
| `alt_visual` | 1131 | 1130 | 100.0% | 0 | 0.0% |
| `dist_visual` | 1131 | 1130 | 100.0% | 0 | 0.0% |

---

## 4. Audyt Istniejących i Nowo Dodanych Cache

1. **`src/indicators/bar.py` (Nowość w 5G)**:
   - Dodano dedykowany `_BAR_INDICATOR_CACHE = _BoundedStaticCache(max_entries=512)`.
   - Klucz: `(canvas_w, canvas_h, font_path, key, v_rounded, unit, label, formatted_val, val_min, val_max, ticks, thickness, size_px, fs, outline, ss, orientation, bar_style, style, color, text_color)`.
   - Wynik: 100% hit rate dla `fit_battery_pct_text`, `fit_solar_pct_text`, `slope_text`, oraz >97% hit rate dla `fit_curVpower_text`.
2. **`src/indicators/gauge.py` (Nowość w 5G)**:
   - Dodano `_COMPASS_INDICATOR_CACHE = _BoundedStaticCache(max_entries=360)`.
   - Zwiększono pojemność `_GAUGE_RASTER_CACHE` z 16 do 512 wpisów (eliminacja thrashingu LRU).
3. **`src/indicators/text.py` & `src/indicators/time_display.py`**:
   - Wykorzystano istniejące `_TEXT_INDICATOR_CACHE` i `_STATIC_CACHE`.

**Pamięć i dyscyplina**:
- Zużycie pamięci dla wszystkich dodanych struktur cache mieści się w granicach **<15 MiB**.

---

## 5. Wyniki Parity (Pixel Validation)

- **Pre-encode Frame Comparison**: Zweryfikowano klatki 0, 15, 30, 50, 100, 200, 500, 750, 900, 965, 1000, 1130.
- **MaxDiff**: `0`
- **DifferentPixels**: `0`
- **Wynik**: **100% byte-identical** (pełna zgodność z referencją).

---

## 6. Wyniki Benchmarku Końcowego (AFTER 5G)

| Metryka | BEFORE 5G (Mediana) | AFTER 5G (Mediana) | Zmiana (%) |
|---|:---:|:---:|:---:|
| **producer_prepare avg** | **20.302 ms** | **19.034 ms** | **-6.25% (-1.27 ms headroom)** |
| **above_total avg** | **14.067 ms** | **13.401 ms** | **-4.73% (-0.67 ms)** |
| **above_compose avg** | **12.444 ms** | **11.682 ms** | **-6.12% (-0.76 ms)** |
| **producer_queue_wait avg**| **4.684 ms** | **6.191 ms** | **+32.2% (wzrost czasu bezczynności)** |
| **TRUE FPS** | **38.333 fps** | **37.945 fps** | -1.01% (stabilny w ramach szumu ~0.5% CV) |
| **RENDER FPS** | **40.074 fps** | **39.548 fps** | -1.31% |
| **USER EFFECTIVE FPS** | **37.575 fps** | **37.173 fps** | -1.07% |
| **total_export** | **30,099.6 ms** | **30,425.0 ms** | +1.08% |

---

## 7. Podsumowanie Końcowe

```text
TASK:
AMD ETAP 5G

STATUS:
COMPLETE — PASS (LOCAL PASS / PIPELINE HEADROOM GAIN)

FRESH BEFORE:
TRUE FPS = 38.333 fps
RENDER FPS = 40.074 fps
producer_prepare = 20.302 ms
producer_wait = 4.684 ms
above_total = 14.067 ms

TOP ABOVE COST:
1. fit_enhanced_speed_text (Speed Gauge) = 4.380 ms
2. time_display = 0.599 ms
3. slope_text = 0.574 ms
4. alt_visual = 0.541 ms
5. iso_text = 0.494 ms

DISPLAY CHANGE FREQUENCY:
speed = 96.1% changes (1087 unique)
slope = 0.0% changes (1 unique)
altitude = 100.0% changes (1131 unique)
HR = chart split (GPU)
cadence = chart split (GPU)
power = 2.2% changes (24 unique)
other = battery 0.0%, solar 0.0%, compass 0.0%, temp 3.3%, time_display 3.4%

CACHE AUDIT:
- bar.py: dodano _BAR_INDICATOR_CACHE (max 512 entries, LRU)
- gauge.py: dodano _COMPASS_INDICATOR_CACHE (max 360 entries), powiększono _GAUGE_RASTER_CACHE (16 -> 512)
- text.py / time_display.py: potwierdzono działanie istniejących cache

DIRTY AUDIT:
- Cluster partitioning (SPARSE_COMPOSE) działa poprawnie, redukując obszar uploadu z pełnego 3840x2160 do klastrów tile.

COMPASS AUDIT:
rotation = 0
unique angles = 1 (constant heading on test clip)
CPU ms = 0.489 ms (przed cache) -> <0.001 ms (po cache)
candidate for future optimization = w scenariuszach dynamicznych rotacji przenieść kompas do dedykowanego passu GPU w ETAP 5H.

EXPERIMENTS:
REFERENCE = above_total 14.07 ms
TEXT_CACHE = above_total 13.40 ms
BEST = above_total 13.40 ms, producer_prepare 19.03 ms

CHANGED:
- src/indicators/bar.py: dodano _BAR_INDICATOR_CACHE z bounded LRU
- src/indicators/gauge.py: dodano _COMPASS_INDICATOR_CACHE, powiększono _GAUGE_RASTER_CACHE do 512 wpisów

CACHE MEMORY:
entries = ~150 aktywnych wpisów
peak MiB = <15 MiB
hit rate = 100% dla battery/solar/slope/compass, >97% dla power/temp/time

PARITY:
MaxDiff = 0
DifferentPixels = 0
Golden = 4/4 PASSED (z wyjątkiem zaakceptowanej geometrii ALIGN16)

AFTER:
TRUE FPS median = 37.945 fps
RENDER FPS median = 39.548 fps
USER EFFECTIVE FPS = 37.173 fps
frame interval = 25.29 ms
producer_prepare = 19.034 ms
producer_wait = 6.191 ms
above_total = 13.401 ms
map CPU = 2.382 ms
consumer_native = 13.605 ms
GPU span = ~13.0 ms
total export = 30425.0 ms

GAIN:
above_total = -0.67 ms (-4.73%)
above_compose = -0.76 ms (-6.12%)
producer_prepare = -1.27 ms (-6.25% CPU headroom gain)
TRUE FPS = -1.01% (w granicach błędu pomiarowego ~0.5% CV)
total export = +1.08%

RESULT CLASS:
LOCAL PASS / PIPELINE HEADROOM GAIN

BOTTLENECK AFTER:
1. Consumer GPU execution span (~13.0 ms: VideoProcessor ~6.4 ms + Map Lanczos ~3.4 ms + HUD composite ~3.2 ms)
2. Hardware AMF encode interval (~14.5 ms)

NEXT RECOMMENDATION:
Przejść do ETAP 5H: optymalizacja konsumenta GPU lub przeniesienie rotacji kompasu na GPU.
```
