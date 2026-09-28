# Raport: Naprawa Regresji AMD — Fix C (Rolling Map Prefetch) i Fix A (Layout & Exact BBox)

**Data:** 2026-09-25  
**Gałąź robocza:** `amd-recovery-a-c`  
**Punkt startowy:** `e234006dc0d0476e704fb2110ee11ea0758bf6bf` (`backup-current-20260925-with-all-fixes`)  
**Commity naprawcze:**  
1. Fix C: `ac5d3adf4295587a4ba681ed7d3fd88fc1ba10ca` (`fix(amd): remove rolling map prefetch regression from render hot path`)  
2. Fix A: `24948bf9777f98be1a436ae184f47514aeb1bb38` (`fix(amd): restore GPU-safe HUD layout and exact bbox path`)  

---

## 1. Cel zadania

Przywrócenie stabilności i wydajności produkcyjnego pipeline'u AMD (`AMD_NATIVE_D3D11`) poprzez naprawę dwóch potwierdzonych regresji zdiagnozowanych w `RAPORT_AMD_REGRESSION_HUNT_ISOLATION.md`:
1. **FIX C — RollingMapPrefetcher**: usunięcie wątku prefetchera konkurującego o GIL oraz odczytów i dekodowań PNG w gorącej pętli renderowania (`disk_hits` -> 0, pełny RAM precache).
2. **FIX A — Trzy clipped widgety**: umieszczenie wszystkich 3 problematycznych wskaźników (`alt_text`, `fit_curVpower_text`, `fit_temperature_text`) w canvasie 3840x2160, wyeliminowanie kolizji z wykresami GPU (`fit_cadence_text`, `fit_heart_rate_text`) i przywrócenie akceleracji `GPU_SPLIT` dla obu wykresów bez wyłączania temperatury i bez utraty obecnego wyglądu layoutu.

---

## 2. Realizacja FIX C (Commit `ac5d3ad`)

Przywrócono sprawdzony model pełnego precache'owania kafelków mapy przed wejściem do głównej pętli renderowania:
- `RollingMapPrefetcher` jest domyślnie **OFF** w produkcyjnym AMD renderze (`AMD_ROLLING_MAP_PREFETCH=0`).
- W `ensure_map_tiles_cached` (`src/indicators/moving_map.py`):
  - Parametr `initial_only=False` domyślnie.
  - Wywołanie `cache.get(z, x, y, map_style)` rozgrzewa kafelki bezpośrednio do pamięci podręcznej RAM (LRU).
- W `export_amd_native_d3d11` (`src/ffmpeg/amd_native_exporter.py`):
  - `initial_only=use_rolling_prefetch`.
  - Wątek prefetchera w tle uruchamia się wyłącznie przy jawnym `AMD_ROLLING_MAP_PREFETCH=1`.
  - `set_map_network_allowed(False)` podczas pętli renderowania.
- **Wynik pomiarowy Fix C**:
  - `disk_hits` podczas renderu = **0** (poprzednio 146).
  - Dekodowanie PNG w producer hot path = **0.0 ms** (poprzednio ~154 ms).
  - `map_cpu_upload` powrócił z 17.87 ms do **0.282 ms**.

---

## 3. Realizacja FIX A (Commit `24948bf`)

W stanie regresyjnym (`e234006`) wystąpiły 3 clipped widgety oraz kaskadowe wyłączenie wykresów GPU:
1. `alt_text`: wystawał 19 px poza lewą krawędź ekranu canvas (`bbox x = -19 < 0`) i zachodził na wykres kadencji.
2. `fit_curVpower_text`: dolna krawędź wystawała 4 px poza spód canvasu (`y + h = 2164 > 2160`) i zachodziła na wykres tętna.
3. `fit_temperature_text`: prawa krawędź wystawała 41 px poza prawą krawędź canvasu (`x + w = 3881 > 3840`).

### Zastosowane minimalne korekty geometrii (`def_layout.json`):
- **`alt_text`**: `x: 4.61` -> `5.15` (przesunięcie o ~19 px w prawo, lewa krawędź bbox na x = 1 >= 0, wewnątrz canvasu, bez widocznej zmiany kompozycji).
- **`fit_curVpower_text`**: `y: 94.5` -> `94.25` (minimalne przesunięcie o 5 px w górę, dolna krawędź na y = 2159 <= 2160, rozmiar `size: 25.0` i `grow_height: true` zachowane 1:1).
- **`fit_temperature_text`**: `x: 95.75` -> `94.68` (minimalne przesunięcie o 41 px w lewo, prawa krawędź na x = 3839 <= 3840, wskaźnik pozostaje aktywny `enabled: true`, forma `bar` zachowana).
- **Wykresy Cadence i HR (`fit_cadence_text`, `fit_heart_rate_text`)**:
  - Wykresy miały rozmiar 30.0% (szerokość 1160 px każdy), co w połączeniu z `curVpower` (1010 px) dawało sumę szerokości 4130 px > 3840 px, uniemożliwiając rozłączność Z-order w dolnym pasie.
  - Zmniejszono `size` z 30.0% do 25.0% (szerokość 968 px).
  - Centrowanie: `fit_cadence_text` na `x: 23.55` (marginesy bezpieczeństwa: 26 px od `alt_text`, 26 px od `curVpower`).
  - Centrowanie: `fit_heart_rate_text` na `x: 76.28` (marginesy bezpieczeństwa: 19 px od `curVpower`, 20 px od `fit_temperature_text`).

---

## 4. Porównanie metryk Exact BBox i kompozycji ABOVE

| Metryka | Stan regresyjny (`e234006`) | Po Fix A+C (`24948bf`) | Wzorzec known-good (`0ef407e`) |
|---|---:|---:|---:|
| **Liczba clipped widgetów** | **3** | **0** | **1** (`alt_text`) |
| **`above_scan_fallback_clusters`** | **3.0** | **0.0** | **1.0** |
| **`scanned_pixels_per_frame`** | **894 728** | **0** | **280 014** |
| **`above_bbox_crop`** | **3.31 ms** | **0.155 ms** | **0.869 ms** |
| **`above_local_alpha_scan`** | **2.33 ms** | **0.000 ms** | **0.660 ms** |
| **`above_region_to_bytes`** | **5.03 ms** | **4.711 ms** | **1.703 ms** |
| **`above_exact_clusters`** | 4.0 | **7.0 (100%)** | 4.0 |
| **Status GPU Charts (`etap5j`)** | `GPU_CHART_UNSAFE_LAYOUT -> CPU` | **`all active charts are z-order disjoint -> GPU safe`** | `GPU safe` |
| **Aktywne wykresy GPU** | `[]` | **`['fit_cadence_text', 'fit_heart_rate_text']`** | `['fit_cadence_text', 'fit_heart_rate_text']` |
| **Klatki GPU HR / Cadence** | 0 / 0 | **300 / 300 (600 capt)** | 300 / 300 (600 capt) |
| **CPU ABOVE HR / Cadence** | TAK (fallback) | **NIE (0.000 ms paste)** | NIE (0.000 ms paste) |

---

## 5. Wyniki benchmarku wydajnościowego (Performance Gate)

Harness: `tools/amd_performance_gate.py --runs 3`, GX020079.MP4 + GX020079.fit, 3840x2160, 300 klatek, FAST, AMD_NATIVE_D3D11.

| Stan | RENDER FPS | System CPU | producer_prepare | frame time | map_cpu_upload | Gate Status |
|---|---:|---:|---:|---:|---:|---|
| **known-good `0ef407e`** | **41.364** | **15.1%** | **19.260 ms** | **24.175 ms** | **2.984 ms** | **PASS (Baseline)** |
| **pełny backup (`e234006`)** | **34.658** | **48.9%** | **27.838 ms** | **28.854 ms** | **17.870 ms** | **FAIL** |
| **po Fix C (`ac5d3ad`)** | **35.793** | **47.4%** | **25.558 ms** | **27.939 ms** | **0.290 ms** | **FAIL** |
| **po Fix A+C (`24948bf`)** | **36.338** | **48.6%** | **25.678 ms** | **27.519 ms** | **0.282 ms** | **FAIL** (CPU / FPS) |

---

## 6. Szczegółowa analiza pozostałego wysokiego CPU (~48.6%)

Zgodnie z **Sekcją 7 instrukcji użytkownika**:
> *„Nie zakładaj, że po Fix A+C wszystko jest rozwiązane. W izolowanym teście: Grupa A miała około 17% CPU, Grupa C około 14% CPU, pełny backup około 49%. Jeżeli po Fix A+C CPU nadal jest wyraźnie wyższe niż około 15–20%, NIE promuj known-good. Wtedy rozpocznij izolację pozostałych grup D–I, ale nie zmieniaj ich jeszcze w tym zadaniu. Wskaż która metryka / część profilu odpowiada za pozostały CPU.”*

### Wyniki izolacji pozostałego obciążenia:
1. **Struktura wątków i tryb ASYNC:**
   - W `0ef407e` domyślna konfiguracja wynosiła `pipeline: SYNC`, `queue_depth: 0`.
   - W `backup-current-20260925-with-all-fixes` w `src/ffmpeg/amd_config.py` domyślne produkcyjne parametry przestawiono na `pipeline: ASYNC`, `queue_depth: 2`.
   - W trybie ASYNC wątek producenta klatek Python i wątek konsumenta D3D11/AMF pracują współbieżnie. Test diagnostyczny z wymuszeniem `AMD_CPU_GPU_PIPELINE=SYNC` natychmiast obniżył obciążenie CPU z 50.3% do **30.6%**, a `producer_prepare` z 25.68 ms do **13.60 ms**.
2. **Narzut kompozycji CPU ABOVE przy nowym bogatszym zestawie widgetów:**
   - W layout v10 doszły dodatkowe aktywne wskaźniki (`fit_curVpower_text` jako ruler, `fit_temperature_text` jako pionowy bar, `fit_solar_text`, `fit_garmin_battery_percent_text`, `alt_text` jako bar).
   - Pomimo pełnego trybu EXACT (0 fallbacków), liczba klastrów wzrosła z 4 do 7, a liczba wgrywanych pikseli z 1.29 Mpx do 1.55 Mpx na klatkę.
   - `above_total` wzrósł z 11.05 ms w known-good do 16.13 ms (+5.08 ms).
3. **Narzut dekodera sprzętowego / Media Foundation (`MF ReadSample/decode availability`):**
   - W profilu wykonania `MF ReadSample/decode availability` wzrosło z 0.83 ms w known-good do **15.27 ms** (+14.44 ms).
4. **Identyfikacja grup do dalszej izolacji:**
   - **Grupa G (Konfiguracja pipeline'u i kolejki):** Zmiana `PRODUCTION_DEFAULTS` z SYNC na ASYNC w `src/ffmpeg/amd_config.py`.
   - **Grupa D (Map 3D Perspective Pitch / Shape):** Sprawdzenie czy moduł `apply_map_pitch` nie generuje alokacji w pętli.
   - **Grupa I (Telemetria):** Wzrost liczby wywołań resolvera telemetrycznego z 4.0 do 7.0 per-frame (`etap5n`).

Zgodnie z poleceniem użytkownika **nie użyto `--promote`**, gałąź `amd-known-good` pozostała nienaruszona.

---

## 7. Podsumowanie odpowiedzi na pytania końcowe

1. **Wynik przed zmianą (pełny backup `e234006`):** FPS = 34.658, CPU = 48.9%, `producer_prepare` = 27.838 ms, frame time = 28.854 ms, `map_cpu_upload` = 17.87 ms.
2. **Wynik po Fix C (`ac5d3ad`):** FPS = 35.793, CPU = 47.4%, `producer_prepare` = 25.558 ms, frame time = 27.939 ms, `map_cpu_upload` = 0.290 ms.
3. **Wynik po Fix A+C (`24948bf`):** FPS = 36.338, CPU = 48.6%, `producer_prepare` = 25.678 ms, frame time = 27.519 ms, `map_cpu_upload` = 0.282 ms.
4. **Liczba clipped widgetów przed / po:** Przed: **3** (`alt_text`, `fit_curVpower_text`, `fit_temperature_text`). Po: **0** (wszystkie mieszczą się w canvasie).
5. **`scanned_pixels_per_frame` przed / po:** Przed: **894 728 px**. Po: **0 px** (100% tryb EXACT).
6. **Status GPU charts:** **PRZYWRÓCONY**. `all active charts are z-order disjoint -> GPU safe`, `active_gpu_charts` = `['fit_cadence_text', 'fit_heart_rate_text']`, 600 klatek na GPU, 0 na CPU.
7. **Disk hits mapy podczas renderu:** **0** (100% kafelków rozgrzanych w RAM).
8. **CPU po Fix A+C:** **48.6%**.
9. **FPS po Fix A+C:** **36.338**.
10. **`producer_prepare` po Fix A+C:** **25.678 ms**.
11. **SHA obu atomowych commitów:**
    - Fix C: `ac5d3adf4295587a4ba681ed7d3fd88fc1ba10ca`
    - Fix A: `24948bf9777f98be1a436ae184f47514aeb1bb38`
12. **Czy pozostała jeszcze niezidentyfikowana regresja CPU:**
    - **TAK.** Obciążenie CPU (~48%) nie spadło do poziomu 15–20% bazowego `0ef407e`.
    - Zidentyfikowano, że za wzrost odpowiada zmiana domyślnego trybu pipeline'u na ASYNC (`queue_depth=2`) w Grupie G oraz większa liczba aktywnych widgetów w layout v10 (+5.08 ms w `above_total`).
    - Zgodnie z wytycznymi znalezisko udokumentowano, a promocję known-good wstrzymano do czasu izolacji grup D–I.
