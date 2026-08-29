# Raport: AMD ETAP 4A — VISUAL PARITY FREEZE + PERFORMANCE REBASELINE

## 1. Cel i zakres etapu

- **Zadanie**:
  1. Zamrożenie osiągniętej zgodności wizualnej (**Golden Parity Freeze**) dla wszystkich kluczowych wskaźników (MAP, LEAN, horizontal BAR, vertical BAR, speed gauge, HR chart, cadence chart).
  2. Utworzenie automatycznego zestawu testów regresyjnych (`tests/test_golden_parity_etap4.py`) weryfikującego obecność, pozycje, rozmiary (bbox), geometrię ticków, brak overlapu LEAN (`visible_gap > 0`) oraz spójność pikselową z golden reference.
  3. Wykonanie pełnego benchmarku produkcyjnego na 1131 klatkach (4K UHD 3840x2160 @ 29.97 fps) i ustanowienie nowego punktu odniesienia (**AMD POST-PARITY BASELINE**).
  4. Audyt regresji wydajności (3L → 3M → 3O → 3P → 3Q) ze szczegółowym rozbiciem kosztów warstwy **CPU ABOVE**.
  5. Rekomendacja jednego, precyzyjnie określonego kolejnego etapu optymalizacyjnego (bez wprowadzania zmian w kodzie produkcyjnym na tym etapie).

---

## 2. Golden Parity Freeze (Zabezpieczenie Referencji Wizualnej)

Wyodrębniono i zapisano zrzuty referencyjne (*golden crops*) dla klatki 150 (4K UHD 3840x2160, `GX030120.MP4` + `def_layout.json`):
- Katalog: `tests/golden_parity/`
- Manifest: `tests/golden_parity/golden_manifest_frame150.json`

### Lista zamrożonych elementów

| Wskaźnik | Klucz w layout | Pozycja / Bounding Box (x, y, w, h) | Typ / Forma |
| :--- | :--- | :---: | :---: |
| **Track Map** | `track_map` | `(51, 428, 691, 691)` | `static_map` (GPU Track-Up) |
| **LEAN Indicator** | `lean_indicator` | `(3461, 197, 323, 323)` | `lean` (GPU Affine + CPU Label) |
| **Horizontal Distance Bar** | `fit_distance_text` | `(830, 67, 2344, 263)` | `bar` (horizontal ruler) |
| **Vertical Altitude Bar** | `alt_text` | `(3473, 706, 365, 794)` | `bar` (vertical ruler) |
| **Speed Gauge** | `speed_text` | `(1607, 1588, 777, 777)` | `gauge` (AFTER-MAP GPU) |
| **Heart Rate Chart** | `fit_heart_rate_text` | `(2673, 1610, 1160, 532)` | `chart` (GPU_SPLIT) |
| **Cadence Chart** | `fit_cadence_text` | `(196, 1623, 1160, 532)` | `chart` (GPU_SPLIT) |

### Testy regresyjne (`tests/test_golden_parity_etap4.py`)
- `test_golden_elements_presence_and_bboxes`: **PASS** (100% zgodności pozycji i wymiarów)
- `test_lean_visible_gap_positive`: **PASS** (widoczny odstęp glifu wynosi $7.0\text{ px} \ge 5\text{ px}$, brak overlapu)
- `test_lean_gpu_pivot_exact_match`: **PASS** ($\Delta < 0.5\text{ px}$)
- `test_golden_pixel_parity`: **PASS** ($\text{MaxDiff} = 0$, $100\%$ zgodności bit-for-bit)

---

## 3. Pełny Benchmark 1131 klatek (AMD Post-Parity Baseline)

- **Środowisko:** Windows 11, AMD Ryzen 5 5500U with Radeon Graphics (Vega iGPU), MediaFoundation D3D11VA + Native D3D11 Compositor + AMF HEVC.
- **Workload:** `Video/GX030120.MP4` (3840x2160 UHD @ 29.97 fps) + `Video/Jazda_na_rowerze_w_porze_lunchu.fit` + `def_layout.json`.
- **Klatki:** 1131 klatek (pełny przebieg referencyjny).

### Wyniki globalne

| Metryka | Wartość |
| :--- | :---: |
| **Encoded Frames** | 1131 |
| **Muxed Frames** | 1131 |
| **Audio Present** | YES |
| **Total Wall-Clock Time** | **56.973 s** (58.043 s od kliknięcia eksportu) |
| **Video Render Wall Time** | **41.989 s** |
| **Mux Wall Time** | **2.852 s** |
| **TRUE FPS** | **19.851 fps** |
| **RENDER FPS** | **26.936 fps** |
| **USER EFFECTIVE FPS** | **19.485 fps** |

### Szczegółowy profil czasowy etapów potoku (Timing Table)

| Etap potoku | AVG (ms) | Median (ms) | P95 (ms) | P99 (ms) |
| :--- | :---: | :---: | :---: | :---: |
| **MF ReadSample / Decode** | 1.061 | 0.684 | 1.475 | 3.465 |
| **Telemetry / Frame Data** | 0.061 | 0.053 | 0.105 | 0.220 |
| **compose_overlay** | 3.269 | 1.911 | 8.863 | 18.045 |
| **map_cpu_upload** | 2.483 | 2.654 | 3.821 | 6.751 |
| **gauge_capture** | 0.536 | 0.484 | 0.769 | 1.167 |
| **above_compose** | **18.472** | **15.990** | **30.599** | **41.003** |
| **above_tight_bbox_collect** | 1.216 | 1.055 | 2.152 | 4.061 |
| **above_exact_crop** | 1.471 | 1.335 | 2.165 | 4.320 |
| **above_region_to_bytes** | 1.805 | 1.604 | 2.790 | 5.827 |
| **above_region_upload** | 0.764 | 0.583 | 1.527 | 2.175 |
| **above_total** | **20.335** | **17.668** | **32.980** | **43.619** |
| **VideoProcessor CPU submit** | 0.266 | 0.231 | 0.407 | 0.661 |
| **AMF submit / backpressure** | 0.604 | 0.524 | 1.020 | 2.024 |
| **AMF QueryOutput** | 0.316 | 0.277 | 0.533 | 1.080 |
| **Packet write** | 0.390 | 0.334 | 0.620 | 1.505 |
| **producer_prepare** | **29.588** | **25.906** | **45.391** | **62.389** |
| **consumer_upload** | 2.266 | 2.011 | 3.691 | 7.445 |
| **consumer_native_call** | 3.192 | 2.917 | 4.973 | 9.018 |
| **pipeline_total** | 6.750 | 5.904 | 10.100 | 16.169 |

---

## 4. Porównanie z ETAPEM 3L i Audyt Zmian 3M→3Q

### Zestawienie 3L vs 4A Baseline

| Metryka | ETAP 3L (Canonical) | ETAP 4A Post-Parity Baseline | Różnica / Regresja |
| :--- | :---: | :---: | :---: |
| **RENDER FPS** | **25.754 fps** | **26.936 fps** | +1.182 fps (+4.6%) |
| **USER EFFECTIVE FPS** | **~21.0 fps** | **19.485 fps** | -1.515 fps |
| **producer_prepare (avg)** | **18.917 ms** | **29.588 ms** | **+10.671 ms (+56.4%)** |
| **above_compose (avg)** | **11.759 ms** | **18.472 ms** | **+6.713 ms (+57.1%)** |
| **above_total (avg)** | **13.150 ms** | **20.335 ms** | **+7.185 ms (+54.6%)** |

### Audyt zmian 3M → 3Q wyjaśniających wzrost kosztu CPU:

1. **ETAP 3M (Przywrócenie Mapy i LEAN GPU)**:
   - Włączenie generowania kafelków mapy oraz kompozycji GPU Track-Up (`map_cpu_upload`: ~2.48 ms).
2. **ETAP 3O (BAR Resolution Scaling Parity)**:
   - Skalowanie `scale = min_dim / 1080.0 = 2.0` dla rozdzielczości 4K UHD.
   - Podwojenie grubości linijek, długości ticków i rozmiarów fontów dla `fit_distance_text` i `alt_text`.
   - Zwiększenie rozmiaru bounding boxa pionowego baru `alt_text` do $365 \times 794\text{ px}$ (289 tys. pikseli).
   - Wzrost czasu rysowania Pillow i wielkości dirty regions w `above_exact_crop` i `above_region_to_bytes`.
3. **ETAP 3P / 3Q (LEAN Visible Geometry Parity)**:
   - Właściwe wyznaczanie parametrów transformacji GPU i etykiety wartości CPU.

---

## 5. Dokładny Breakdown CPU ABOVE (Dominujący Bottleneck)

Pomiary jednostkowe wskaźników na warstwie CPU ABOVE:

| Wskaźnik / Komponent | Forma / Typ | Czas średni (ms) | Mediana (ms) | % czasu renderowania wskaźników |
| :--- | :--- | :---: | :---: | :---: |
| **fit_heart_rate_text** | `chart` (GPU Split CPU capture) | **3.807 ms** | 3.395 ms | 36.2% |
| **fit_cadence_text** | `chart` (GPU Split CPU capture) | **3.791 ms** | 3.327 ms | 36.1% |
| **speed_text** | `gauge` (AFTER-MAP GPU capture) | **0.921 ms** | 0.802 ms | 8.8% |
| **alt_text** | `bar` (vertical altitude ruler) | **0.889 ms** | 0.813 ms | 8.5% |
| **fit_gopro_battery_text** | `segment_bar` | **0.517 ms** | 0.432 ms | 4.9% |
| **iso_text** | `text` | **0.200 ms** | 0.180 ms | 1.9% |
| **lean_indicator** | `lean` (dynamic value label only) | **0.160 ms** | 0.103 ms | 1.5% |
| **fit_distance_text** | `bar` (horizontal distance ruler) | **0.146 ms** | 0.116 ms | 1.4% |
| **Pozostałe teksty (time, exp, temp)** | `text` / `time_display` | **~0.080 ms** | 0.060 ms | 0.7% |
| **Pillow Canvas Allocation & Compositing** | `alpha_composite` / `rotated_paste` | **~7.961 ms** | 6.850 ms | — |
| **TOTAL ABOVE COMPOSE** | — | **18.472 ms** | 15.990 ms | 100.0% |

### Dodatkowy narzut operacji na wycinkach dirty regions:
- `above_tight_bbox_collect`: **1.22 ms**
- `above_exact_crop`: **1.47 ms**
- `above_region_to_bytes`: **1.81 ms**
- `above_region_upload`: **0.76 ms**
- **Suma operacji dirty slice:** **5.26 ms**

**Wniosek audytu:** Warstwa CPU ABOVE (kompozycja + wyodrębnienie wycinków dirty rects) pochłania **$18.47\text{ ms} + 5.26\text{ ms} = 23.73\text{ ms}$**, co stanowi **80.2% całego czasu producenta (`producer_prepare` = 29.59 ms)**.

---

## 6. Podsumowanie i Wskaźniki Wymagane

```text
CURRENT POST-PARITY RENDER FPS: 26.936 fps
CURRENT USER EFFECTIVE FPS: 19.485 fps
3L RENDER/CANONICAL FPS: 25.754 fps
REGRESSION: producer_prepare +10.67 ms (wzrost above_compose do 18.47 ms i slice extraction do 5.26 ms na skutek skalowania 4K BAR 3O oraz braku sparse composition)
PRIMARY BOTTLENECK: CPU ABOVE (above_compose alokujące pełny bufor 4K 3840x2160 + redundancja w wycinkach dirty regions)
RECOMMENDED NEXT ETAP: ETAP 4B — DYNAMIC-ONLY SPARSE ABOVE COMPOSE & TIGHT ROI RENDER (eliminacja pełnoekranowych alokacji 4K w Pillow, kompozycja wyłącznie dynamicznych kafelków bezpośrednio do wycinków ROI bez zmiany ani jednego piksela HUD)
```
