# Raport: Profiling Komponentów CPU ABOVE (AMD Native D3D11 Pipeline)

Data: 2026-09-16  
Środowisko: `C:\_DEV\SportCamHUD`  
Gałąź: `amd-bikeridehud`  
Oracle: `C:\_DEV\TeleM` (READ-ONLY)  

---

## 1. Wymagane Kluczowe Wskaźniki

```text
ABOVE_TOTAL_AVG=14.570
PRODUCER_PREPARE_AVG=25.842

TOP_1_WIDGET=speed_text
TOP_1_AVG_MS=3.398

TOP_2_WIDGET=fit_garmin_battery_percent_text
TOP_2_AVG_MS=2.086

TOP_3_WIDGET=alt_text
TOP_3_AVG_MS=1.671

RECOMMENDED_NEXT_GPU_WIDGET=fit_garmin_battery_percent_text
CASE=CASE B — COST DISTRIBUTED ACROSS MANY SMALL WIDGETS
```

*(Uwaga: Wśród widgetów renderowanych w 100% programowo na CPU i wklejanych na canvas ABOVE — bez istniejącego GPU path — ranking to: 1. `fit_garmin_battery_percent_text` [2.086 ms], 2. `alt_text` [1.671 ms], 3. `fit_distance_text` [1.110 ms]).*

---

## 2. Środowisko i Konfiguracja Produkcyjna

Wykonano dokładnie jeden pełny przebieg kontrolny w produkcyjnej ścieżce GUI:
`SportCamHUD.py -> GUI -> RenderMixin -> AMD child process -> amd_native_exporter -> telem_amd_native.dll -> AMF`.

- **Zestaw danych**: `Video/GX020079.mp4` + `Video/GX020079.fit`
- **Rozdzielczość**: 3840x2160 (4K UHD)
- **Klatki**: 300 klatek / 10.0 s @ 29.97 fps
- **Kodek**: HEVC AMF
- **Parametry produkcyjne AMD**:
  - `AMD_QUEUE_DEPTH=2`
  - `AMD_CPU_GPU_PIPELINE=ASYNC`
  - `AMD_VP_PROCESSOR_RING_SIZE=1`
  - `AMD_ABOVE_BATCHED=0`
  - `AMD_AFTER_MAP_ALT_VISUAL_GPU=0`
  - `AMD_AFTER_MAP_GAUGE_GPU=1` (AUTO/GPU, niezmienione)
  - `AMD_AFTER_MAP_CHART_GPU=1` (GPU_SPLIT, niezmienione)
  - `AMD_GPU_MAP_ROTATE=1` (GPU, niezmienione)

---

## 3. Wyniki Akceptacyjne Eksportu (Acceptance Criteria)

```text
FRAMES:          300/300 (100%)
DROPPED:         0
AMF ERRORS:      0
D3D11 ERRORS:    0
CHILD EXITCODE:  0
FINAL MP4 SIZE:  85,375,163 bajtów
```

---

## 4. Pełny Ranking Komponentów CPU ABOVE

Pomiar wykonano precyzyjnymi licznikami `time.perf_counter_ns()` wokół każdego aktywnego widgetu w `compositor.py` na przestrzeni 300 klatek produkcyjnych.

| Pozycja | WIDGET | AVG MS | P50 MS | P90 MS | P95 MS | P99 MS | Max MS | % ABOVE_TOTAL | ACTIVE FRAMES |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | `speed_text` | 3.398 | 3.186 | 4.318 | 4.824 | 6.701 | 8.968 | 23.3% | 300 |
| 2 | `fit_garmin_battery_percent_text` | 2.086 | 2.042 | 2.583 | 2.840 | 3.310 | 4.293 | 14.3% | 300 |
| 3 | `alt_text` | 1.671 | 1.263 | 2.632 | 3.219 | 6.138 | 17.697 | 11.5% | 300 |
| 4 | `fit_distance_text` | 1.110 | 0.951 | 1.626 | 2.335 | 3.473 | 5.096 | 7.6% | 300 |
| 5 | `exposure_text` | 0.799 | 0.441 | 1.890 | 2.122 | 2.634 | 3.730 | 5.5% | 300 |
| 6 | `fit_curVpower_text` | 0.729 | 0.473 | 1.402 | 1.690 | 2.047 | 5.198 | 5.0% | 300 |
| 7 | `fit_heart_rate_text` | 0.522 | 0.481 | 0.684 | 0.786 | 1.300 | 2.510 | 3.6% | 300 |
| 8 | `fit_cadence_text` | 0.336 | 0.303 | 0.436 | 0.518 | 1.080 | 2.129 | 2.3% | 300 |
| 9 | `fit_solar_text` | 0.323 | 0.295 | 0.432 | 0.489 | 0.807 | 1.022 | 2.2% | 300 |
| 10 | `iso_text` | 0.216 | 0.113 | 0.440 | 1.017 | 1.388 | 1.991 | 1.5% | 300 |
| 11 | `fit_gopro_battery_text` | 0.118 | 0.098 | 0.164 | 0.217 | 0.337 | 0.942 | 0.8% | 300 |
| 12 | `temp_text` | 0.102 | 0.089 | 0.144 | 0.176 | 0.278 | 0.339 | 0.7% | 300 |
| 13 | `custom_texts` | 0.002 | 0.002 | 0.003 | 0.004 | 0.005 | 0.005 | 0.0% | 300 |

---

## 5. Główne Składowe Czasowe Potoku ABOVE

| Składowa | Średnia (AVG MS) | P95 MS | P99 MS | Max MS |
|:---|:---:|:---:|:---:|:---:|
| `above_total` | **14.570** | 19.257 | 22.505 | 27.616 |
| `above_compose` | **12.429** | 16.498 | 19.997 | 24.818 |
| `above_bbox_crop` | **0.083** | 0.117 | 0.158 | 0.242 |
| `above_region_to_bytes` | **2.058** | 3.509 | 4.772 | 5.732 |
| `above_region_upload` | **1.574** | 2.997 | 4.712 | 6.831 |
| `producer_prepare` | **25.842** | 31.220 | 36.253 | 403.006 |
| `regional_clear_ms` | **0.873** | 1.516 | 2.378 | 3.746 |

---

## 6. Analiza i Rekomendacja

### 6.1. Weryfikacja Szacunków Historycznych
Zgodnie z hipotezą zadania, historyczne szacunki okazały się całkowicie rozbieżne z aktualnym stanem produkcyjnym:
- `alt_visual` / `alt_text`: historycznie szacowane na ~3.2 ms, aktualny realny koszt to **1.671 ms**.
- `compass`: 0.0 ms (brak w layoucie produkcyjnym).
- `fit_enhanced_speed_text`: 0.0 ms (`enabled: false` w produkcyjnym `def_layout.json`).
- `slope_text`: 0.0 ms (brak w layoucie produkcyjnym).

### 6.2. Status Widgetu Prędkościomierza (`speed_text`)
`speed_text` zajmuje średnio **3.398 ms** na CPU podczas wywołania `render_value_indicator()`. Kafelek ten jest następnie przechwytywany (`above_gpu_capture`) i przesyłany do GPU, gdzie jest blendowany natywnie (`AMD_AFTER_MAP_GAUGE_GPU=1`). Zgodnie z zasadą **HARD STOP**, ścieżka gauge pozostaje nienaruszona.

### 6.3. Rekomendowany Kandydat do Kolejnej Optymalizacji: `fit_garmin_battery_percent_text`
Kandydat spełnia wszystkie 5 kryteriów decyzyjnych:
1. **Wysoki koszt CPU**: Średnio **2.086 ms / klatkę** (P95: 2.84 ms, Max: 4.29 ms), co stanowi **14.3% całego czasu ABOVE_TOTAL** — najwyższy pojedynczy koszt wśród komponentów czysto CPU.
2. **Aktywny na wszystkich klatkach**: 300/300 klatek (100%).
3. **Brak obecnego GPU path**: Brak implementacji segment_bar w potoku D3D11.
4. **Możliwa reprodukcja 1:1 bez zmiany wyglądu**: Pasek składa się ze stałej geometrii segmentów i etykiety tekstowej, idealny pod dedykowany kafelek lub split static/dynamic.
5. **Sensowny koszt transferu/update**: Niewielki prostokątny obszar o niskiej zmienności w czasie (aktualizacja segmentów baterii zachodzi rzadko, co pozwala na niemal zerowy narzut transferu dynamicznego).

---

## 7. Podsumowanie i Klasyfikacja

**Klasyfikacja:** `CASE B — COST DISTRIBUTED ACROSS MANY SMALL WIDGETS`  
*(Żaden pojedynczy widget CPU nie przekracza 15% czasu warstwy ABOVE; koszt rozkłada się równomiernie pomiędzy pasek baterii Garmina [2.09 ms], linijkę wysokości [1.67 ms], linijkę dystansu [1.11 ms] oraz grupę mniejszych wskaźników tekstowych [~0.8-0.1 ms]).*
