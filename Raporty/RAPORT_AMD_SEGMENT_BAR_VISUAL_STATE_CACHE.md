# Raport: Canonical Visual-State Cache dla Widgetów Segment Bar (AMD D3D11 Pipeline)

Data: 2026-09-16  
Środowisko: `C:\_DEV\BikeRideHUD`  
Gałąź: `amd-bikeridehud`  
Dataset: `Video/GX010298.MP4` + `Video/GX010298.fit` (3840x2160, 300 klatek, HEVC AMF)  

---

## 1. Wymagane Kluczowe Wskaźniki

```text
BATTERY_RAW_VALUE_CHANGES=300
BATTERY_VISUAL_STATE_CHANGES=6
BATTERY_CACHE_HITS=295
BATTERY_CACHE_MISSES=6
BATTERY_HIT_RATIO=98.01%

POWER_RAW_VALUE_CHANGES=212
POWER_VISUAL_STATE_CHANGES=22
POWER_CACHE_HITS=279
POWER_CACHE_MISSES=22
POWER_HIT_RATIO=92.69%

LOOKUP_AVG_MS=0.0526

ABOVE_TOTAL_A=15.354
ABOVE_TOTAL_B=13.056

PRODUCER_PREPARE_A=24.043
PRODUCER_PREPARE_B=22.886

FPS_A=38.116
FPS_B=38.923
FPS_DELTA=+0.807 (+2.12%)

VISUAL_DIFF_PIXELS=0

CASE=CASE A — SEGMENT_BAR VISUAL-STATE CACHE VALIDATED FOR SLOW + FAST DATA
```

---

## 2. Podsumowanie Wdrożenia i Architektura

Wyeliminowano wąskie gardło generic cache w module `src/indicators/widget_cache.py`, w którym sygnatura renderera `segment_bar` była nadmiernie czuła na zmiany zmiennoprzecinkowe `raw_value` (interpolowane ułamki telemetryczne).

### Nowa definicja Canonical Visual State:
Sygnatura wizualna wyliczana jest bezpośrednio z wyjścia silnika renderującego `_render_segments`:
1. `value_text`: Sformatowany ciąg znaków (np. `"51%"`, `"111 W"`).
2. `active`: Całkowita liczba aktywnych segmentów (`int: 0..segments`).
3. `partial_state`: Stopień wypełnienia segmentu ułamkowego (tylko w trybie `fill_mode == "partial"`).
4. `marker_x`: Dyskretna pozycja pikselowa markera w poziomie (jeśli włączony).
5. `cfg_frozen`: Pełna zamrożona konfiguracja geometrii, stylów, kolorów, fontów i progów.

### Izolacja instancji (Per-Instance Cache):
Każdy wskaźnik `segment_bar` w layoucie posiada odrębny bufor i niezależne metryki:
- **Instancja 1 (wolnozmienna)**: `fit_garmin_battery_percent_text`
- **Instancja 2 (szybkozmienna)**: `fit_curVpower_text`

---

## 3. Wyniki Benchmarku A/B (Real GUI Path, 3840x2160, 300 klatek)

- **RUN A**: `AMD_CPU_WIDGET_CACHE=0` (Cache OFF)
- **RUN B**: `AMD_CPU_WIDGET_CACHE=1` (Cache ON, Canonical Visual State)

| Metryka | RUN A (Cache OFF) | RUN B (Cache ON) | Delta (B - A) | Względna zmiana |
|:---|:---:|:---:|:---:|:---:|
| **Wall Time** | 7.871 s | 7.708 s | -0.163 s | **-2.07%** |
| **True FPS** | **38.116** | **38.923** | **+0.807** | **+2.12%** |
| **Render FPS** | 49.511 | 48.598 | -0.913 | -1.84% |
| **above_total avg** | **15.354 ms** | **13.056 ms** | **-2.298 ms** | **-14.97%** |
| **above_compose avg** | **12.932 ms** | **10.355 ms** | **-2.577 ms** | **-19.93%** |
| **producer_prepare avg** | **24.043 ms** | **22.886 ms** | **-1.157 ms** | **-4.81%** |

---

## 4. Statystyki Per-Instance Cache (RUN B)

| Wskaźnik | Typ danych | Raw Changes | Visual Changes | Hits | Misses | Hit Ratio | Lookup Avg | Render Avg |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Garmin Battery %** | Wolnozmienny | 300 | 6 | 295 | 6 | **98.01%** | 0.0376 ms | 2.4112 ms |
| **curVPower** | Szybkozmienny | 212 | 22 | 279 | 22 | **92.69%** | 0.0675 ms | 2.0595 ms |

---

## 5. Weryfikacja Poprawności i Pixel Parity

### 5.1 Testy jednostkowe / logiczne (`tests/test_generic_widget_cache.py`)
- **Slow-changing sequence**: `83.12 -> 83.14 -> 83.16 -> 83.51` -> `MISS, HIT, HIT, MISS` (**PASS**).
- **Fast-changing sequence**: `100 -> 101 -> 102 -> 103` -> `MISS, MISS, MISS, MISS` (**PASS**, 0 opóźnienia).
- **Layout/Style Invalidation**: Zmiana `segment_count`, `min/max`, `color`, `thresholds`, `font`, `orientation`, `geometry`, `precision`, `unit` natychmiast generuje `MISS` (**PASS**).
- **Per-Instance Isolation**: Niezależne bufory dla baterii i mocy (**PASS**).

### 5.2 Pixel Parity na Wyjściowym Strumieniu Wideo MP4
Porównano klatki kontrolne oraz klatki przejść wartości mocy (frames 0, 35, 36, 37, 38, 50, 150, 250, 299) pomiędzy RUN A i RUN B:
- Wszystkie klatki: `diff_pixels = 0`, `max_diff = 0`, `MAE = 0.0000` (**100% BITWISE EXACT MATCH**).
- Brak jakichkolwiek artefaktów, ghostingu czy jednoklatkowego opóźnienia.

---

## 6. Dyscyplina Flag Produkcyjnych

Flaga `AMD_CPU_WIDGET_CACHE` pozostaje domyślnie **wyłączona (`0`)** w konfiguracji produkcyjnej do momentu zakończenia pełnej serii optymalizacji.
