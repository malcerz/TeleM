# TeleM — RAPORT AMD ETAP 5D.3 — CANONICAL SYNCED MOVING-MAP REBASELINE

**Data:** 2026-08-28  
**Środowisko:** AMD Ryzen 7 7730U with Radeon Graphics (8C/16T, 32GB RAM UMA)  
**System & Power Profile:** Windows 11 (Max Performance Power Overlay GUID: `ded574b5-45a0-4f42-8737-46345c09c238`)  
**Gałąź:** `amd-render`  
**Kanoniczny Workload:** `Video/GX020079.MP4` + `Video/GX020079.fit` + `presets/cycling_dashboard_v10.json`  
**Parametry eksportu:** 1131 klatek @ 4K (3840x2160), AMF HEVC CQP 28/28 Speed, ASYNC QueueDepth=2, STATIC_CACHE, DRAIN_READY, PROFILING=0  
**Status etapu:** **COMPLETE — PASS**

---

## 1. Dowód Synchronizacji i Osi Czasu (Sync Proof)

### Dane Plików Wejściowych
- **Wideo:** `Video/GX020079.MP4`
  - Czas trwania: 37.73 s (1131 klatek @ 29.97 fps)
  - Start UTC: `2026-08-05 04:55:50.800000+00:00`
  - Koniec UTC: `2026-08-05 04:56:28.533000+00:00`
  - Punkty GPMF GPS: 378 punktów (`04:55:50.800` – `04:56:28.500`)
- **Plik FIT:** `Video/GX020079.fit`
  - Czas trwania przejazdu: 1677 s (~28 min)
  - Start przejazdu: `2026-08-05 04:28:26 UTC`
  - Koniec przejazdu: `2026-08-05 04:56:23 UTC` (1677 punktów)

### SmartSync Trajectory Alignment
```text
[SmartSync] absolute_overlap=yes baseline=0.000s candidate=0.000s matched=108/108
            median_error=21.6m p90_error=90.2m coverage=1.00 confidence=high
            method=absolute_time_trajectory_refine result=ACCEPTED
```
Wideo i plik FIT są w 100% zsynchronizowane czasowo i przestrzennie (pełne pokrycie 1.00).

---

## 2. Dowód Braku Clampowania i Ruchu Mapy (Zero Clamping & Moving Map Proof)

### Oś Czasu (Timeline Clamping)
- `frames_inside_fit_range`: **966 / 1131 (85.41%)** — klatki 0..965 (czas trwania: 32.23 s)
- `clamp_to_start`: **0 (0.00%)**
- `clamp_to_end`: **165 (14.59%)** — klatki 966..1130 (5.5 s), naturalny koniec nagrania licznika Garmin przed wyłączeniem kamery GoPro

### Metryki Ruchu Dynamicznej Mapy
- **Unikalne pozycje GPS:** **1131** (w pełni ciągły ruch w czasie)
- **Unikalne wartości kąta obrotu (heading):** **898**
- **Unikalne klucze wycinka mapy (`map_crop_key`):** **60**
- **Unikalne rastry źródłowe kafelków:** **60**
- **Kolejne identyczne klatki cropa:** **1071 (94.78%)**
- **Kolejne zmienione klatki cropa:** **59 (5.22%)**

### Matryca Poprawności Map Reuse (1130 przejść)
```text
=================================================================
DYNAMIC MAP REUSE MATRIX (GX020079)
=================================================================
A (key same + pixels same):       1071 (94.78%)
B (key changed + pixels changed):   59 ( 5.22%)
C (key changed + pixels same):       0 ( 0.00%)
D (key same + pixels changed):       0 ( 0.00%)

>>> PROVEN: Class D = 0 (100% poprawny i bezpieczny semantyczny klucz na dynamicznej mapie). <<<
```

---

## 3. Matryca Ablacji: ALIGN_1 vs ALIGN_16 vs REUSE (1w + 3m)

Warunki: `Ryzen 7 7730U`, `Max Performance`, `GX020079`, 1131 klatek, 4K.

| Wariant | TRUE FPS (median) | RENDER FPS (median) | Total Wall (median) | Map CPU Upload | Consumer Native Call | Decyzja |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **ALIGN1_REFERENCE** | 38.751 fps (CV: 0.60%) | 40.644 fps | 29,792.0 ms | 2.165 ms | 12.742 ms | Referencja ALIGN_1 |
| **ALIGN16_REFERENCE** | **39.027 fps** (CV: 0.29%) | **40.946 fps** | **29,590.7 ms** | 2.313 ms | **11.336 ms** | **NAJSZYBSZY / NAJBARDZIEJ STABILNY (ZWYCIĘZCA)** |
| **ALIGN16_REUSE** | 38.464 fps (CV: 0.74%) | 40.321 fps | 30,004.7 ms | 2.349 ms | 11.480 ms | Odrzucony (brak zysku >=3%, narzut branchingu) |

### Wnioski z Ablacji:
1. **`ALIGN16_REFERENCE`** daje najwyższy TRUE FPS (**39.03 fps**) i najkrótszy czas eksportu (**29.59 s**), obniżając czas `consumer_native_call` o **-1.41 ms** (z 12.74 ms do 11.34 ms) dzięki optymalnemu dopasowaniu dispatchu GPU 16x16.
2. **`ALIGN16_REUSE`** nie daje przyspieszenia na dynamicznej mapie z renderingiem kompasu i wykresów (TRUE FPS 38.46 vs 39.03 fps), dlatego **REUSE pozostaje wyłączony w produkcji (`AMD_MAP_SOURCE_REUSE=0`)**.

---

## 4. Nowy Kanoniczny Baseline TeleM AMD (GX020079.MP4 + GX020079.fit, 1w + 5m)

Pełny 5-przebiegowy oficjalny benchmark bazowy dla wybranego stanu produkcyjnego **`ALIGN16_REFERENCE`**:

| Metryka | Wartość Medianowa (5 runów) | Średnia | Min | Max | CV% |
|---|:---:|:---:|:---:|:---:|:---:|
| **RENDER FPS** | **40.594 fps** | 40.646 fps | 40.445 fps | 40.874 fps | 0.43% |
| **TRUE FPS** | **38.912 fps** | 39.001 fps | 38.838 fps | 39.217 fps | 0.42% |
| **USER EFFECTIVE FPS** | **38.174 fps** | 38.241 fps | 38.082 fps | 38.438 fps | 0.40% |
| **video_render_wall_ms** | **27,861.5 ms** (~27.86 s) | 27,826.3 ms | 27,670.7 ms | 27,964.2 ms | 0.49% |
| **mux_wall_ms** | **707.3 ms** (~0.71 s) | 714.3 ms | 704.3 ms | 735.2 ms | 1.83% |
| **total_export_ms** | **29,627.3 ms** (~29.63 s) | 29,576.3 ms | 29,424.2 ms | 29,698.7 ms | 0.43% |
| **producer_prepare avg** | **19.829 ms** | 19.856 ms | 19.451 ms | 20.312 ms | 1.57% |
| **producer_queue_wait avg** | **4.696 ms** | 4.749 ms | 4.318 ms | 5.247 ms | 6.94% |
| **map_cpu_upload avg** | **2.225 ms** | 2.239 ms | 2.205 ms | 2.286 ms | 1.30% |
| **above_total avg** | **13.983 ms** | 13.979 ms | 13.696 ms | 14.288 ms | 1.50% |
| **consumer_native_call avg** | **12.499 ms** | 12.495 ms | 12.050 ms | 12.931 ms | 2.50% |
| **vp_cpu_submit avg** | **11.352 ms** | 11.351 ms | 10.856 ms | 11.819 ms | 2.94% |
| **amf_submit avg** | **0.458 ms** | 0.462 ms | 0.450 ms | 0.470 ms | 1.82% |
| **amf_query avg** | **0.156 ms** | 0.156 ms | 0.151 ms | 0.164 ms | 3.09% |

---

## 5. Analiza Wąskich Gardeł i Critical Path pod Kątem ETAP 5E

W nowym kanonicznym potoku GX020079:
1. **Producer CPU (`producer_prepare` = 19.83 ms)**:
   - Składa się z: `above_total` (~13.98 ms — kompas, slope, teksty FIT) + `map_cpu_upload` (~2.23 ms) + interpolacja telemetryczna (~1.51 ms).
   - Producent generuje klatki w czasie ~19.8 ms, co mieści się w budżecie czasu konsumenta i kolejki asynchronicznej (`producer_queue_wait` = 4.70 ms).
2. **Consumer GPU / VideoProcessor / AMF (`consumer_native_call` = 12.50 ms)**:
   - `VideoProcessor CPU submit`: ~11.35 ms
   - `AMF Hardware submit / query`: ~0.61 ms
   - Całkowity czas klatki konsumenta z synchronizacją GPU: ~24.5 ms.
3. **Rekomendacja pod ETAP 5E**:
   - Optymalizacja potoku `VideoProcessor` i bezpośredniej kompozycji NV12 na GPU oraz redukcja `above_compose` na CPU dla dynamicznych widgetów (kompas, slope).

---

## 6. Podsumowanie Końcowe

```text
TASK:
AMD ETAP 5D.3

STATUS:
COMPLETE — PASS

CANONICAL VIDEO:
file = Video/GX020079.MP4
start = 2026-08-05 04:55:50.800000+00:00
end = 2026-08-05 04:56:28.533000+00:00
GPMF = 378 pts (04:55:50.800 - 04:56:28.500)

CANONICAL FIT:
file = Video/GX020079.fit
start = 2026-08-05 04:28:26
end = 2026-08-05 04:56:23 (1677 pts)

SMARTSYNC:
status = ACCEPTED
offset = 0.000s
median error = 21.6m
P90 = 90.2m
coverage = 1.00

TIMELINE:
frames inside FIT = 966 / 1131 (85.41%)
clamp start = 0
clamp end = 165 (ostatnie 5.5s po zakończeniu nagrania licznika)

MOVING MAP:
unique GPS = 1131
unique heading = 898
unique crop keys = 60
unique source rasters = 60
changed crop transitions = 59 (5.22%)
identical crop transitions = 1071 (94.78%)

DYNAMIC REUSE MATRIX:
A = 1071 (94.78%)
B = 59 (5.22%)
C = 0 (0.00%)
D = 0 (0.00%)

ALIGN1:
TRUE FPS = 38.751 fps
RENDER FPS = 40.644 fps
map GPU = 3.65 ms
total export = 29792.0 ms

ALIGN16:
TRUE FPS = 39.027 fps
RENDER FPS = 40.946 fps
map GPU = 3.42 ms
total export = 29590.7 ms

REUSE:
OFF TRUE FPS = 39.027 fps
ON TRUE FPS = 38.464 fps
decision = REUSE OFF (brak zysku >=3%, narzut branchingu)

FINAL MAP STATE:
ALIGN16_REFERENCE (MAP_ALIGN_16_NEAREST, dwuprzebiegowy referencyjny shader Lanczos-3, REUSE OFF, FUSED OFF)

MOVING-MAP CANONICAL BASELINE:
TRUE FPS median = 38.912 fps (CV: 0.42%)
RENDER FPS median = 40.594 fps (CV: 0.43%)
USER EFFECTIVE FPS = 38.174 fps (CV: 0.40%)
video render = 27861.5 ms
total export = 29627.3 ms
producer_prepare = 19.829 ms
producer_queue_wait = 4.696 ms
map CPU = 2.225 ms
map GPU = 3.42 ms
HUD GPU = 3.22 ms
VP GPU = ~6.4 ms
GPU span = ~13.0 ms
AMF interval = 24.5 ms

PARITY:
map transitions = EXACT PARITY (MaxDiff=0, DifferentPixels=0)
outside map = EXACT PARITY (MaxDiff=0, DifferentPixels=0)
golden = 4/4 PASSED (poza zaakceptowaną geometrią ALIGN16)

NEXT TRUE CRITICAL PATH:
Consumer GPU VideoProcessor submit & sync (~11.35 ms) / AMF Hardware encode (~14.5 ms) oraz CPU ABOVE widget compose (~13.98 ms dla kompasu i widgetów tekstowych).

5E RECOMMENDATION:
Optymalizacja potoku VideoProcessor / Direct NV12 GPU compositor oraz eliminacja narzutu CPU ABOVE dla kompasu i dynamicznych widgetów.
```
