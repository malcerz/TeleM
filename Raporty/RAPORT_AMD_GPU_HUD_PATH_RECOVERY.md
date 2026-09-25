# Raport: Odzyskanie Właściwej Zoptymalizowanej Ścieżki AMD GPU HUD (Path Recovery)

**Data:** 2026-09-21  
**Backend:** AMD Native D3D11 (`AMD_NATIVE_D3D11`)  
**Branch:** `amd-bikeridehud`  
**Środowisko:** Windows 11, Ryzen 7 5800X / Radeon RX 6700 XT, 4K HEVC Direct Mux  
**Status:** **PASS — CASE A (STRETCH >=40 FPS OSIĄGNIĘTY: 42.202 FPS)**

---

## 1. Architektura & Odpowiedzi Obowiązkowe

```text
EXISTING_GPU_HUD_PATH=YES
EXISTING_REGION_COMPOSITOR=YES
EXISTING_DIRTY_REGION_UPLOAD=YES
CURRENT_PRODUCTION_PATH_USES_THEM=YES
```

### WHY_EXISTING_FAST_PATH_NOT_USED:
W dotychczasowym kodzie produkcyjnym istniała kaskada dwóch krytycznych defektów routingu layoutu w `src/ffmpeg/amd_native_exporter.py`:

1. **Wyłączenie Mapy deaktywowało cały GPU Pipeline:**
   W `_amd_layout_roles` podział layoutu na `map_above_layout` i `compose_layout` był ściśle obwarowany warunkiem:
   `if gpu_map_enabled and track_map_cfg and track_map_cfg.get("enabled", True):`.
   Gdy mapa była wyłączona (`map_enabled = False` lub `--no-map`), `map_above_layout` było ustawiane na `None`.
   Ponieważ akcelerowane sprzętowo wykresy GPU (`fit_cadence_text`, `fit_heart_rate_text`), GPU speed gauge (`speed_text`) oraz wieloregionowy dirty-region compositor opierają się na warunku `if map_above_layout is not None:`, wyłączenie mapy **całkowicie wyłączało wszystkie ścieżki GPU** i zrzucało wszystkie 30 wskaźników do pojedynczego, gigantycznego canvasu Pillow (`compose_layout`).

2. **Pozycja `track_map` na końcu layoutu psuła podział nawet przy włączonej mapie:**
   W `_ordered_map_layout_parts` wskaźniki były dzielone ściśle wg kolejności kluczy: przed mapą -> `below`, za mapą -> `above`. W produkcyjnym layoucie `GX010303.layout.json` (oraz wielu innych presetach) wskaźnik `track_map` znajdował się na 30. pozycji (z 31), co powodowało, że `above_indicators` było puste (`{}`), degradując render do pełnego canvasu CPU!

3. **Daisy-chain bounding boxów scalał canvas do 100% 4K:**
   W `_dirty_rects_from_bboxes` każdy z 14–30 wskaźników otrzymywał margines 40px. Nakładające się bounding boxy scalały się w jeden gigantyczny prostokąt `(0, 0, 3840, 2160)` (33.18 MB). W każdej klatce Pillow wykonywał `crop()` (7.1 ms) oraz `.tobytes()` (23.0 ms) = **30.1 ms marnowane na kopiowanie 33.2 MB w CPU**, dławiąc proces do 21.5 FPS.

---

## 2. Wdrożona Poprawka (Minimal Fix)

W pliku `src/ffmpeg/amd_native_exporter.py`:
1. `_ordered_map_layout_parts`:
   - Jeśli `track_map` jest na końcu listy lub go brak, overlay dashboardu (wykresy HR/kadencji, speed gauge, odczyty telemetryczne) jest kierowany do `above_indicators`, natomiast statyczne tła (`time_display`, `dist_visual`) pozostają w `below_indicators`.
2. `_amd_layout_roles`:
   - Zawsze rozdziela layout na `compose_layout` (poniżej mapy) oraz `map_above_layout` (powyżej mapy), niezależnie od tego, czy mapa jest włączona czy wyłączona.
   - Gwarantuje, że akcelerowane wykresy GPU, GPU speed gauge oraz wieloregionowy dirty compositor działają zawsze.

---

## 3. Pomiary i Porównanie A/B (300 klatek, 4K HEVC)

| Metryka | STAN PRZED POPRAWKĄ | STAN PO POPRAWCE | Zmiana / Zysk |
|---|---|---|---|
| **ATLAS_BYTES** | 33 177 600 B (100% 4K) | 4 730 624 B (14.9% 4K) | **-85.7%** |
| **BYTES_COPIED_PER_FRAME** | 33 177 600 B | 4 730 624 B | **-85.7%** |
| **CPU_HUD_RENDER_MS** | 17.60 ms | 14.49 ms | -3.11 ms |
| **BUFFER_COPY_MS** | 27.82 ms | 2.35 ms | **-25.47 ms (-91.5%)** |
| **PRODUCER_PREPARE_MS** | 46.39 ms | 19.04 ms | **-27.35 ms (-59.0%)** |
| **BARE_FPS (HUD OFF, MAP OFF)**| 42.867 FPS | 42.827 FPS | Invariant |
| **HUD_FPS (HUD ON, MAP OFF)**  | **21.480 FPS** | **42.202 FPS** | **+96.5% (+20.72 FPS)** |
| **EFFECTIVE_FPS (HUD ON, MAP OFF)** | 18.230 FPS | **35.698 FPS** | **+95.8%** |
| **MAP_FLAT_CONTROL_FPS** | 16.716 FPS | **25.698 FPS** | **+53.7% (+8.98 FPS)** |
| **MAP_FLAT_COST_MS** | 32.31 ms | **20.95 ms** | -11.36 ms |

### Klasyfikacja Wyniku:
```text
CASE=CASE A — >=40 FPS recovered (42.202 FPS)
```
Cel minimalny (>=35 FPS), target (>=38 FPS) oraz stretch (>=40 FPS) zostały w pełni przekroczone. Koszt narzutu pełnego HUD-u względem trybu BARE wynosi obecnie zaledwie **0.625 FPS (1.4% overhead)**!

---

## 4. Weryfikacja Poprawności Wizualnej (Bit-for-Bit Parity)

Wyekstrahowano i porównano piksel w piksel 10 klatek referencyjnych z testu 300f (`scratch/amd_atlas_regression/300f_hud_on.mp4` vs `scratch/amd_gpu_hud_recovery/300f_hud_after.mp4`):

| Klatka | Max Diff | MAE | Diff Pixels | Parity Status |
|---|---|---|---|---|
| **Frame 000** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 015** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 030** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 060** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 090** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 120** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 150** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 180** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 240** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |
| **Frame 290** | 0 | 0.0000 | 0 (0.000%) | **PASS (100% IDENTICAL)** |

```text
HUD_GEOMETRY_PARITY=PASS
HUD_VALUE_PARITY=PASS
HUD_STYLE_PARITY=PASS
```
Różnica wizualna wynosi dokładnie 0 pikseli.

---

## 5. Pamięć i Stabilność Cache

```text
HUD_CACHE_ENTRIES_START=1
HUD_CACHE_ENTRIES_END=1
MEMORY_GROWTH_MB=0.0 (po ustabilizowaniu inicjalizacji AMF/D3D11)
ONE_RENDER_PROGRESS_BAR=True
ONE_RENDER_PROGRESS_TEXT=True
```

---

## 6. Dyscyplina Czasowa (Execution-Time Breakdown)

```text
TOTAL_STAGE_WALL_TIME=26 min
AUDIT_TIME=7 min
REPRO_TIME=3 min
IMPLEMENTATION_TIME=4 min
VALIDATION_TIME=12 min
LONGEST_SINGLE_COMMAND_SECONDS=21.6 s
TARGET_TOTAL_TIME <= 60 min: PASS (26 min / 60 min)
HARD_MAX_TIME <= 90 min: PASS
```

---

## 7. Wnioski dla Kolejnego Etapu (Koszt Mapy)

Po odzyskaniu bazowej wydajności HUD na poziomie 42.2 FPS:
- Włączenie mapy na płasko (`pitch=0`) daje **25.70 FPS** (poprzednio 16.72 FPS).
- Sam narzut mapy wynosi dokładnie **20.95 ms** w pipeline producenta CPU.
- Kolejnym etapem optymalizacji może być zaadresowanie renderera mapy, mając już całkowicie zdrowy, 42-klatkowy baseline HUD.
